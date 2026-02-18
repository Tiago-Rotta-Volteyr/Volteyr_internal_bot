"""
Airtable sub-agent: self-correcting StateGraph that retries on API/column errors (max 3).
The LLM reads "Error: ..." as observation and can correct table/field names.
"""
import logging
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.tools.airtable import search_airtable
from app.tools.utils import get_table_schema

FLOW = "[FLOW]"
LOG = logging.getLogger(__name__)

# Subgraph state: messages (append) + retry counter
class AirtableSubgraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    retries_used: int


AIRTABLE_MAX_RETRIES = 3


def _airtable_system_prompt() -> str:
    schema = get_table_schema()
    return f"""Tu es l'expert Airtable. Tu interprètes la demande utilisateur et appelles l'outil search_airtable avec les bons paramètres (table_name, query, sort_by, sort_direction, max_records).

---

### INTELLIGENT COLUMN MAPPING (CRITICAL)

Avant de générer une formule Airtable, tu dois ANALYSER l'input de l'utilisateur :

1. **Détecte le TYPE de la donnée recherchée :**
   - Est-ce un **Email** ? (contient '@' et '.')
   - Est-ce un **Numéro de téléphone** ? (contient des chiffres)
   - Est-ce un **Nom d'entreprise** ?
   - Est-ce un **Nom de personne** ?

2. **Sélectionne la colonne ADAPTÉE dans le schéma :**
   - Si Input = **Email** -> Tu DOIS chercher dans une colonne nommée `{{Email}}`, `{{Courriel}}`, `{{Email Address}}`. N'utilise JAMAIS `{{Nom}}` ou `{{Nom Complet}}` pour un email.
   - Si Input = **Entreprise** -> Cherche dans `{{Entreprise}}`, `{{Société}}`, `{{Company}}`.
   - Si Input = **Nom** -> Cherche dans `{{Nom}}`, `{{Nom Complet}}`.

3. **Stratégie de Formule :**
   - Pour un **Email** (Recherche exacte) : Utilise `{{Email}} = 'bob@mail.com'` (Plus fiable que SEARCH).
   - Pour un **Nom** (Recherche partielle) : Utilise `SEARCH(LOWER('bob'), LOWER({{Nom}}))`.

### EXEMPLES DE COMPORTEMENT ATTENDU :
- User: "Qui a l'email toto@gmail.com ?"
- Toi: Je détecte un email. Je cherche la colonne `{{Email}}`. Formule: `{{Email}} = 'toto@gmail.com'`

- User: "Infos sur l'entreprise Tesla"
- Toi: Je détecte une entreprise. Je cherche la colonne `{{Company}}`. Formule: `SEARCH('tesla', LOWER({{Company}}))`

---

{schema}

Règles d'appel outil :
1. Utilise UNIQUEMENT les noms de tables et de champs listés dans le schéma ci-dessus.
2. Si l'outil renvoie "Error:" (champ introuvable, field not found, etc.), lis le message d'erreur : il peut indiquer les champs disponibles. Corrige ta requête avec un champ ou une table valide puis réessaie.
3. Pour "qui a payé le plus" / max : query vide, sort_by=champ montant (ex. CTV, Montant), sort_direction='desc', max_records=1.
4. Pour lister tous les enregistrements : query vide.
5. Tu as au plus {AIRTABLE_MAX_RETRIES} tentatives en cas d'erreur ; après ça, renvoie une synthèse de l'erreur à l'utilisateur.

---

### 1. FILTRAGE INTELLIGENT (obligatoire)
- Ne recrache JAMAIS toutes les colonnes disponibles.
- Analyse l'intention de l'utilisateur :
  - S'il demande "une liste de clients", "les clients", "liste des X" : affiche UNIQUEMENT Nom (ou équivalent), Statut, et éventuellement CA/Revenue. Cache les emails, téléphones et IDs sauf si explicitement demandés.
  - S'il demande "les contacts", "coordonnées", "emails" : ALORS affiche emails et téléphones.
- Sois minimaliste par défaut : 3 à 5 colonnes max sauf si la question exige plus.

### 2. FORMAT DE RÉPONSE — TABLEAU OU TEXTE SELON LE NOMBRE DE LIGNES

**Peu de résultats (1 à 3 lignes de données)** — répondre en TEXTE, pas en tableau :
- Si l'outil renvoie un tableau avec seulement 1, 2 ou 3 lignes de données (en excluant la ligne d'en-têtes et la ligne de séparation | :--- |), ne recopie PAS le tableau.
- Réponds en prose : une ou quelques phrases naturelles qui expliquent le résultat. Exemples :
  - "Le projet qui t'a rapporté le plus est [Nom du projet], avec [montant/chiffre]."
  - "Les 3 projets de ce client sont : [Nom 1], [Nom 2] et [Nom 3]. Le plus récent est [X]."
  - "C'est [Client X] avec qui ça s'est le mieux passé (CA de [montant])."
- **Quand la question porte sur un montant (qui a payé le plus, CA, etc.)** : le tableau renvoyé par l'outil contient une colonne avec les valeurs en euros/devise (celle que tu as utilisée pour le tri, ou tout champ de type currency/number du schéma). Tu DOIS lire la valeur de cette colonne dans la ligne résultat et l'indiquer dans ta réponse. Ne dis pas seulement "c'est le client X" — dis "c'est le client X, avec [valeur de la colonne montant]". Si le nom de la colonne n'est pas évident (ex. CTV, CA), le type dans le schéma (currency, number) t'indique quelle colonne contient le montant.
- Sois direct, lisible et adapté à la question posée. Pas de tableau, pas de liste à puces : du texte fluide.

**Beaucoup de résultats (4 lignes ou plus)** — utiliser un TABLEAU MARKDOWN :
- Recopie le tableau INTÉGRALEMENT dans ta réponse, sans le convertir en liste. Garde la syntaxe | col1 | col2 | avec les retours à la ligne.
- Une courte phrase d'intro (ex. "Voici les clients :") puis le tableau brut. Ne mets pas le tableau dans un bloc de code (pas de ```).
- Si tu dois présenter toi-même plusieurs items dans ce cas, utilise un tableau Markdown avec en-têtes et | :--- |."""


def _build_airtable_graph() -> StateGraph:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([search_airtable])

    def agent_node(state: AirtableSubgraphState) -> dict[str, Any]:
        user_content = ""
        if state["messages"]:
            last = state["messages"][-1]
            user_content = (getattr(last, "content", None) or "")[:200]
        LOG.info("%s airtable_subgraph agent IN user_content_preview=%s", FLOW, user_content[:100] if user_content else "")
        messages = [SystemMessage(content=_airtable_system_prompt())] + state["messages"]
        response = llm.invoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            LOG.info("%s airtable_subgraph agent OUT tool_calls=%s args=%s", FLOW, [t.get("name") for t in tool_calls], [t.get("args") for t in tool_calls])
        else:
            content_preview = (getattr(response, "content", None) or "")[:150]
            LOG.info("%s airtable_subgraph agent OUT end (no tool_calls) content_preview=%s", FLOW, content_preview[:80] if content_preview else "")
        return {"messages": [response]}

    tools = [search_airtable]
    tool_node = ToolNode(tools)

    def tool_node_wrapper(state: AirtableSubgraphState) -> dict[str, Any]:
        # Log de la requête complète (args envoyés à search_airtable)
        last_msg = state["messages"][-1] if state["messages"] else None
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                a = tc.get("args") or {}
                LOG.info("%s Airtable (sous-graphe): query complète → table=%s query=%s sort_by=%s sort_direction=%s max_records=%s", FLOW, a.get("table_name"), a.get("query"), a.get("sort_by"), a.get("sort_direction"), a.get("max_records"))
        else:
            LOG.info("%s Airtable (sous-graphe): outil search_airtable appelé", FLOW)
        out = tool_node.invoke(state)
        last_content = ""
        if out.get("messages"):
            last_msg = out["messages"][-1]
            if isinstance(last_msg, ToolMessage):
                last_content = (last_msg.content or "") if isinstance(last_msg.content, str) else str(last_msg.content)
        if "Error" in last_content or "error" in last_content.lower():
            LOG.info("%s Airtable (sous-graphe): recherche → erreur", FLOW)
        elif "No records" in last_content or not last_content.strip():
            LOG.info("%s Airtable (sous-graphe): recherche → aucun enregistrement", FLOW)
        else:
            lines = last_content.count("\n") + 1
            LOG.info("%s Airtable (sous-graphe): recherche → %s", FLOW, f"{lines} lignes ressorties" if lines > 1 else "1 ligne ressortie")
        is_error = "Error" in last_content or "error" in last_content.lower()
        retries = state.get("retries_used", 0)
        new_retries = retries + 1 if is_error else retries
        return {"messages": out["messages"], "retries_used": new_retries}

    def after_tool_route(state: AirtableSubgraphState) -> Literal["agent", "__end__"]:
        last = state["messages"][-1] if state["messages"] else None
        if not isinstance(last, ToolMessage):
            return "__end__"
        content = (last.content or "") if isinstance(last.content, str) else str(last.content)
        is_error = "Error" in content or "error" in content.lower()
        retries = state.get("retries_used", 0)
        if is_error and retries < AIRTABLE_MAX_RETRIES:
            return "agent"
        return "__end__"

    graph = StateGraph(AirtableSubgraphState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node_wrapper)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _tools_condition, {"tools": "tools", "__end__": END})
    graph.add_conditional_edges("tools", after_tool_route, {"agent": "agent", "__end__": END})
    return graph


def _tools_condition(state: AirtableSubgraphState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1] if state["messages"] else None
    if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
        return "__end__"
    return "tools"


def get_airtable_graph():
    """Compiled Airtable subgraph (no checkpointer). Invoke with state = { messages: [HumanMessage(...)], retries_used: 0 }."""
    return _build_airtable_graph().compile()
