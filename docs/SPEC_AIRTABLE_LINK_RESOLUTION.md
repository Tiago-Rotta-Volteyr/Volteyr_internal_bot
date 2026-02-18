# Spécification : Résolution des champs lien Airtable (Bot Airtable)

## 1. Contexte et problème

### Comportement actuel
- L’outil `search_airtable` interroge une table Airtable et renvoie les champs des enregistrements sous forme de tableau Markdown.
- Les champs de type **lien vers un autre enregistrement** (linked records) sont renvoyés par l’API Airtable comme une **liste d’IDs** (ex. `['recXXXXXXXXXXXXXX']`).
- L’utilisateur voit donc des IDs dans les réponses (ex. dans la table *Projet*, un champ *Client* affiche `recXXX...` au lieu du nom du client).

### Objectif
- Lorsqu’une requête retourne des données contenant des **IDs de liens** (vers une autre table), le bot ne doit **pas afficher ces IDs**.
- À la place, il doit **résoudre** chaque lien : aller chercher l’enregistrement lié dans la table cible et afficher une **valeur lisible** (ex. nom de l’entreprise, nom du client, ou champ principal de la table liée).

---

## 2. Comportement attendu

### Règle principale
- **Détection** : après avoir récupéré les enregistrements d’une table, repérer les champs dont la valeur est une liste d’IDs Airtable (format `rec...`) ou un seul ID, et dont le type dans le schéma est un type « lien ».
- **Résolution** : pour chaque tel champ, déterminer la **table liée** (celle vers laquelle pointe le lien), puis pour chaque ID :
  - récupérer l’enregistrement correspondant dans cette table ;
  - extraire un **champ d’affichage** (voir § 4) ;
  - remplacer l’ID (ou la liste d’IDs) par cette valeur texte (ou une liste de valeurs, ou une chaîne concaténée).

### Exemple
- **Avant** : Table *Projet*, champ *Client* → `recABC123`
- **Après** : Table *Projet*, champ *Client* → `Entreprise SA` (ou `Dupont` si on choisit le champ « Nom » de la table *Client*)

### Affichage dans le tableau Markdown
- **Un seul lien** : afficher une seule chaîne (ex. `Entreprise SA`).
- **Plusieurs liens** : afficher soit une liste séparée par des virgules, soit une seule cellule avec les noms concaténés (ex. `Client A, Client B`), selon la lisibilité souhaitée.

---

## 3. Détection des champs lien

### Côté API Airtable
- Les champs de type **lien vers d’autres enregistrements** ont le type :
  - `multipleRecordLinks` (plusieurs enregistrements liés) ;
  - ou équivalent « single link » si applicable dans le schéma.
- La valeur renvoyée dans `fields` pour ces champs est :
  - une **liste de chaînes** `['recXXX', 'recYYY']`, ou
  - une **chaîne** `'recXXX'` (selon la config du champ).

### Côté schéma (pyairtable / Meta API)
- Le schéma de la base expose pour chaque champ :
  - `type` (ex. `multipleRecordLinks`) ;
  - des **options** pouvant contenir `linkedTableId` (ID de la table liée).
- Il faut **mapper** `linkedTableId` vers le **nom de table** utilisé dans l’app (ex. via la liste `AIRTABLE_TABLE_NAMES` ou un mapping ID → nom).

### Algorithme de détection
1. Pour la table interrogée, récupérer le schéma (déjà disponible ou à charger).
2. Pour chaque champ du schéma :
   - si le type est `multipleRecordLinks` (ou équivalent lien) → noter le nom du champ et la table liée (`linkedTableId` → nom).
3. Pour chaque enregistrement retourné par la requête :
   - pour chaque champ marqué « lien » :
     - si la valeur est une liste de chaînes dont les éléments ressemblent à des IDs Airtable (`rec...`), ou une seule chaîne `rec...`, alors **résoudre** ce champ (voir § 5).

---

## 4. Champ à afficher pour la table liée

### Règle par défaut
- Utiliser le **champ principal (primary field)** de la table liée comme valeur d’affichage (souvent le « nom » ou le titre de l’enregistrement).

### Personnalisation possible
- Permettre une **configuration** (ex. par table liée) pour choisir un autre champ d’affichage :
  - ex. pour la table *Client* : préférer le champ **« Entreprise »** ou **« Nom »** s’il existe.
- Format de config suggéré (ex. dans `.env` ou config) :
  - `AIRTABLE_LINK_DISPLAY_FIELDS` : mapping `TableLiée:ChampAffichage` (ex. `Client:Entreprise`, `Projet:Nom`).
- Si le champ configuré n’existe pas ou est vide, **fallback** sur le champ principal.

---

## 5. Flux de résolution (où et comment)

### Où implémenter
- **Dans l’outil** `search_airtable` (ou dans une fonction dédiée appelée par lui), **après** la récupération des enregistrements et **avant** la construction du tableau Markdown.
- Pas besoin d’un nouvel appel outil côté LLM : la résolution est **automatique** et transparente pour l’agent.

### Étapes détaillées
1. Obtenir les enregistrements (comme aujourd’hui) : `records = table.all(...)` (ou équivalent avec filtre / tri).
2. Pour la table courante, récupérer la liste des champs de type lien et, pour chacun, la table liée (nom) et le champ d’affichage (config ou primary).
3. Pour chaque enregistrement :
   - `fields = record.get("fields", {})`
   - Pour chaque champ « lien » :
     - `value = fields.get(field_name)`
     - Si `value` est une liste d’IDs (ou un seul ID), normaliser en liste `ids = [value]` si besoin.
     - Pour chaque `record_id` dans `ids` :
       - Appeler l’API Airtable pour récupérer l’enregistrement `record_id` dans la **table liée** (ex. `api.table(base_id, linked_table_name).get(record_id)` ou équivalent batch).
       - Extraire le champ d’affichage de cet enregistrement.
     - Remplacer `fields[field_name]` par la chaîne affichable (ex. `", ".join(display_values)`).
4. Passer les `fields` modifiés à `_records_to_markdown_table(...)` comme aujourd’hui.

### Gestion des erreurs
- Si un ID lié ne peut pas être résolu (enregistrement supprimé, accès refusé, table inconnue) : afficher un libellé fixe (ex. `"(inconnu)"` ou `"—"`) pour cet ID, sans faire échouer toute la requête.
- Si la table liée n’est pas dans `AIRTABLE_TABLE_NAMES`, on peut soit ignorer la résolution pour ce champ (garder l’ID), soit tenter quand même avec l’ID de table du schéma (si on a un moyen de récupérer les enregistrements par ID).

---

## 6. Schéma et API Airtable

### Récupération du schéma
- Déjà en place : `get_table_schema()`, `get_primary_field_name()`, etc. dans `app/tools/utils.py`.
- À ajouter ou réutiliser :
  - Une fonction qui retourne, pour une table donnée, la liste des champs de type lien **et** pour chacun le `linkedTableId` (ou le nom de la table liée si on a un mapping ID → nom).

### Récupération d’un enregistrement par ID
- Avec pyairtable : `table.get(record_id)` pour un enregistrement donné (si l’API le permet).
- Sinon : `table.all(formula="RECORD_ID() = 'recXXX'")` ou équivalent pour récupérer un enregistrement par ID.
- Pour **plusieurs IDs** (plusieurs liens) : privilégier un **batch** ou des appels groupés pour limiter le nombre de requêtes (ex. récupérer tous les IDs uniques du champ, puis une requête par table liée avec un filtre `OR(RECORD_ID()='id1', RECORD_ID()='id2', ...)` si supporté).

---

## 7. Résumé des modifications à prévoir

| Fichier / zone | Modification |
|----------------|--------------|
| **Schéma / config** | Pouvoir obtenir, pour chaque table, les champs de type lien + table liée (nom) + champ d’affichage (optionnel). |
| **`app/tools/utils.py`** | Ajouter une fonction du type `get_link_fields_config(table_name) -> list[{field_name, linked_table_name, display_field}]`. S’appuyer sur le schéma Airtable (type `multipleRecordLinks`, options `linkedTableId`). |
| **`app/tools/airtable.py`** | Après obtention des `records`, avant `_records_to_markdown_table` : pour chaque record, pour chaque champ lien, résoudre les IDs vers la valeur d’affichage et remplacer dans `fields`. Gérer les erreurs et le fallback. |
| **Config (optionnel)** | Variable d’environnement ou config pour le mapping « table liée → champ d’affichage » (ex. `Client:Entreprise`). |
| **Prompt / agent** | Aucun changement obligatoire : l’outil renvoie déjà un tableau Markdown ; une fois les liens résolus, l’agent affiche naturellement les noms au lieu des IDs. |

---

## 8. Critères de succès

- Pour une requête sur la table *Projet* avec un champ *Client* lié à la table *Client* :
  - la colonne *Client* du tableau Markdown affiche le **nom** (ou l’entreprise) du client, et **jamais** l’ID `rec...`.
- Idem pour tout autre champ lien dans toute table configurée.
- En cas d’erreur de résolution (ID invalide, table absente), l’utilisateur voit un libellé de fallback et non une erreur bloquante.

---

## 9. Implémentation (réalisée)

- **Config** : `AIRTABLE_LINK_DISPLAY_FIELDS` (optionnel) dans `.env`, format `TableLiée:ChampAffichage` séparés par des virgules. Ex. : `Client:Entreprise,Projet:Nom` pour afficher le champ « Entreprise » pour les liens vers la table Client et « Nom » pour les liens vers Projet.
- **utils.py** : `get_link_fields_config(table_name)` retourne la liste des champs lien avec `field_name`, `linked_table_name`, `display_field` (config ou champ principal de la table liée).
- **airtable.py** : `_resolve_link_fields(api, base_id, table_name, records)` modifie les `fields` des enregistrements en remplaçant les IDs par les valeurs affichables ; cache par `(linked_table_name, record_id)` pour limiter les appels API ; fallback `"(inconnu)"` en cas d’erreur.
- Les trois chemins (list all, full scan, formula search) appellent `_resolve_link_fields` avant `_records_to_markdown_table`.

---

*Document de spécification – implémentation réalisée selon ce document.*
