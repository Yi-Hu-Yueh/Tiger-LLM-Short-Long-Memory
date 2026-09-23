# 記憶實作落差與目標架構計畫

本文件保留已核准 typed-engine 架構、schema/persistence 歷史與原始六階段實作計畫。文件狀態：`APPROVED_IMPLEMENTATION_PLAN`。原始 Architecture B typed canonical engine、schema v4 與 deterministic transition architecture 仍獲核准且已實作；model-facing target 已由 `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` 的 Architecture D Grounded Claim-Shape Semantic IR v2 明確 supersede。Semantic IR v1只保留人工rollback，舊13-key不得再作未來target。

## 1. Executive Summary

本文件最初記錄的runtime baseline以`stable memory_id + free-text content`為主；其後核准typed canonical engine、schema v4、deterministic transitions、History/revision/Proposal/Clarification與rendering。新的target不丟棄該engine，而是在上游加入application-owned Canonical Slot Registry、constrained slot/entity IR、Architecture D grounding、Architecture B preconditions及deterministic Risk Engine；changed write只可走`AUTO_COMMIT_ALLOWED` atomic commit或default `HUMAN_REVIEW_REQUIRED` Semantic Confirmation。

使用者已核准 **B. Hybrid：保留 stable ID，為選定 state type 加入 typed canonical state**（`POLICY-05`）。目標支援 `ST-SCALAR`、`ST-SET`、`ST-COUNT`、`ST-RECORD`；`ST-RELATION` 在本原型由 typed set membership 表示，不建 relation table；`ST-PENDING` 與 `ST-HISTORY` 同步保存 typed operation/state，clarification維持獨立控制狀態。既有自由文字資料維持 legacy，不做猜測性轉換。

原始盤點辨識的 15 個 runtime gaps、44 個 semantic-contract gaps 與 17 個 automated-test coverage gaps 保留為歷史證據，不應改寫成從未存在。後續 boundary work 由已核准的簡化計畫分階段導入；任何當下 implementation/test 狀態仍須在實作任務重新驗證，不得只依本文件歷史結果宣稱。

## 2. Governance Baseline

Semantic Confirmation Governance Part 2前已完整讀取六份文件；下表是本次變更前fresh SHA256 baseline，不是變更後expected hash：

| 文件 | 狀態 | SHA256 |
|---|---|---|
| `AGENTS.md` | project instructions | `683EB40F3DAB6E6C3A2B1BEA3CA2DE01648E45C10AEB87758611C6929427704F` |
| `MEMORY_CONSISTENCY_SPEC.md` | `APPROVED_PROJECT_GOVERNANCE` | `806E58D6837086DD2CF92DBA23A9E8A63037AA759EB2F22553BBEA24ACDADEDD` |
| `MEMORY_SEMANTIC_CONTRACTS.md` | `APPROVED_PROJECT_GOVERNANCE` | `776E17CAF4F10818EF731F180442C59167EEC2252C70F30370C88D3AAC2C4108` |
| `MEMORY_ACCEPTANCE_SUITE.md` | `APPROVED_PROJECT_GOVERNANCE` | `38B6FC3190B7835C44E4E13E147255B915C37458745698A22DCED6D3B0FA690E` |
| `MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` | `APPROVED_BOUNDARY_SIMPLIFICATION_PLAN` | `326B494175213CA7BDE87CF0CE430E45E0C8C9E69D8D5FB9998BF53EA2ED3D5D` |
| `MEMORY_IMPLEMENTATION_GAP_PLAN.md` | `APPROVED_IMPLEMENTATION_PLAN` | `318F075553FDEB625F0A90F32D1468CE4FC59C4E5E188A30F4986FC55ECB4DF3` |

六份文件已完成`POLICY-16`及`POLICY-18`–`POLICY-22`cross-document reconciliation。Architecture D grounding、registry-constrained IR、Count/Set authority、deterministic risk routing、selective confirmation、immutable proposals、schema v6 direction及frozen benchmark STOP rule是累積邊界。Prompt/runtime/tests尚未實作此target；屬implementation gap而非governance conflict。

- Affected invariants：`INV-01`–`INV-33`；new work直接影響`INV-27`–`INV-33`。
- Affected semantic contracts：全部76個`MSC-*`；新增8個`MSC-ONTOLOGY/RISK/BENCHMARK-*`contracts。
- Affected acceptance cases：canonical`#1`–`#20`與`AD-01`–`AD-20`保持，`SC-01`–`SC-20`保留Human Review path，新增`OR-01`–`OR-20`。
- Task classification：`specification-changing governance update`；不做 implementation change。
- Governance conflict status：`NO`。

### 2.1 Boundary-plan supersession rule

`MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md` supersedes 本文件中所有要求 DeepSeek 直接輸出固定 13-key decision、exact canonical operation/evidence、`PROPOSE` policy choice、clarification ID 或 deterministic reply 的未來設計。此 supersession 只作用於 model-facing boundary；本文件的 typed canonical state、schema v4、stable IDs、Current/History/Proposal/Clarification persistence、revision、transaction、renderer、validator 與 deterministic transition engine 全部保留。

若兩份 plan 對 model-facing protocol 不同，以 boundary plan 為準。若差異涉及 user-visible semantics、authoritative state 或安全政策，不能套用 supersession，必須停止並依三份治理文件 reconciliation。

### 2.2 Architecture D approved implementation target

Architecture D 是未來production write boundary；Architecture B仍是下游typed execution/precondition architecture。核准順序固定為：

```text
one DeepSeek call
    -> constrained Semantic IR v2 slot/entity/claim extraction
    -> strict structural validator
    -> exact source-grounding validator
    -> Canonical Slot Registry resolution
    -> deterministic claim-shape compiler / family / operation derivation
    -> Architecture B typed-precondition resolver
    -> deterministic Risk Engine
       -> AUTO_COMMIT_ALLOWED -> atomic commit
       -> HUMAN_REVIEW_REQUIRED -> Semantic Confirmation Proposal
          -> local Confirm / structured Correct / Cancel
          -> transaction-time revalidation -> atomic commit
```

Grounding採current-turn exact spans；numeric provenance不證明`五 -> 5`。Known slot由registry derive family/key/label/risk；model只選supplied `slot_id`或`UNKNOWN_SLOT`及candidate entity/target。Changed result一律risk-classified；NOOP/non-write bypass。Diagnostics privacy與v1 manual rollback限制不變。

## 3. Current Runtime Architecture

本節保留schema v3/v4歷史。下一核准方向是additive schema v6，在適用Current/History/Proposal canonical identity加入nullable `slot_id,registry_version,entity_id`；legacy readable、no guessed backfill、no reinterpret old semantic_key，stable `memory_id` lineage不變。

目標正常回合先讀snapshot/context，再做一次DeepSeek呼叫，完成structure/grounding/registry/compiler/preconditions/risk後才短交易寫入。Auto route原子寫成功turn/History/Current/revision；review route只存proposal與turn，後續local Confirm短交易commit。遠端呼叫期間不持有write transaction。現行runtime尚未實作registry/risk/schema v6。

DeepSeek 目前輸出整段 `content` 的 `ADD/UPDATE/DELETE/NOOP`、一個 optional proposal、以及 `freeform|memory` answer route。應用程式可確定性驗證 ownership、stable ID、revision、欄位形狀、容量、精確內容重複、衝突、交易與 render；但無 typed state，無法驗證「Bob 是否屬於正確集合」、「4→3 是否有 admissible evidence」、「更新一個 record field 是否保留 siblings」或「兩段不同 prose 是否同一 semantic slot」。

## 4. Target Runtime Architecture

目標資料流：

```text
SQLite snapshot (typed + legacy) + recent session context
    -> one DeepSeek constrained slot/entity Claim-Shape Semantic IR v2
    -> strict structural validation
    -> application-owned unique exact claimed-literal resolution
    -> authoritative source_start/source_end and exact slice derivation
    -> exact current-turn source-grounding validation
    -> Canonical Slot Registry resolution
    -> deterministic claim-shape compiler/family/operation derivation
    -> existing Architecture B typed precondition resolution
    -> deterministic Risk Engine
    -> AUTO_COMMIT_ALLOWED short atomic SQLite commit
       or HUMAN_REVIEW_REQUIRED immutable proposal -> local resolution -> commit
    -> deterministic typed/legacy rendering
```

DeepSeek只決定intent、supplied canonical slot/UNKNOWN_SLOT、candidate entity/target、claim shape、operand semantic role與exact `claimed_literal`、genuine ambiguity、numeric interpretation及allowed prose；不負責authoritative offset counting。Application對每個required literal計算exact occurrences，只有恰一個時衍生authoritative `source_start/source_end`與slice；zero=`LITERAL_NOT_FOUND`、multiple=`LITERAL_AMBIGUOUS`並整個executable changed write fail closed。Application另owns registry validation/metadata/family/operation/risk。Python仍不解析中文主詞、不normalize、不fuzzy match、不選first occurrence、不修補模型語意；任何wrong shape/type/slot/version/resolution/grounding/policy/precondition均review或fail closed。

對`CARDINALITY_ASSERTION`，model可選exact numeral token或exact contiguous numeral-plus-directly-associated-classifier quantity phrase（例如`五`或`五位`），並分離提供model-semantic `canonical_value`。Human/preregistered oracle負責判斷兩者是否保留同一asserted cardinality；application仍只計算exact occurrences並原樣保留literal，不解析／剝除classifier、不normalize、不repair，也不接受任意周邊noun phrase。此narrow Count rule不得泛化至R05 `色。`等Scalar semantic-boundary error。

保留每回合最多一次正常DeepSeek call、local SQLite、兩使用者、cross-session long-term memory、Current/History/Pending、revision guard與原子交易。Confirm/Cancel仍為零call。User負責確認exact rendered interpretation；confirmation不證明objective truth。

### 4.1 Slot Registry, identity, and schema v6 target

Minimal `SlotDefinition` fields：`slot_id,entity_scope,typed_family,value_type,allowed_claim_shapes,allowed_operations,grounding_required,default_display_label,risk_class,auto_commit_allowed`。Initial registry only：`user.office.location`,`vehicle.color`,`pet.name`,`group.members`,`group.member_count`,`ownership.owner_profile.name`,`ownership.owner_profile.address`,`user.favorite_drink`,`user.birth_month`,`desk.floor`,`device.phone.model`,`person.residence.location`。

`memory_id` remains lineage authority；`slot_id` is versioned property schema；`entity_id` is application-owned stable instance identity。Ordinals are resolution language, not IDs。Ontology-managed `semantic_key` is application-derived and equals canonical `slot_id`; `display_label` is registry-owned。Schema v6 adds nullable `slot_id,registry_version,entity_id` to applicable Current/History/Proposal canonical identity；legacy rows readable, no guessed backfill or old-key reinterpretation。

Registry-v1 exact implementation data：`user.office.location=辦公室位置`；`vehicle.color=車輛顏色`；`pet.name=寵物名字`；`group.members=群組成員`；`group.member_count=群組人數`；`ownership.owner_profile.name=所有權人姓名`；`ownership.owner_profile.address=所有權人地址`；`user.favorite_drink=最愛飲料`；`user.birth_month=出生月份`；`desk.floor=書桌所在樓層`；`device.phone.model=手機型號`；`person.residence.location=居住地點`。Phase 1 MUST encode these exact constants and exact `semantic_key=slot_id` lookup；不得algorithmic label generation、runtime translation、user-prose derivation、fuzzy/alias或model output。Changing a label requires explicit registry-version/governance change。Entity-scoped definition stores only generic label；entity name remains separate presentation data。

### 4.2 Risk and benchmark target

Risk Engine inputs：validated slot, entity scope, operation, claim shape, grounding result, typed-precondition result, registry version, slot risk policy。Outputs：`AUTO_COMMIT_ALLOWED`,`HUMAN_REVIEW_REQUIRED`, or existing non-write/fail-closed。Default review；model confidence never authorizes。Auto requires every`POLICY-21`condition。Unknown slot/entity, ambiguity, destructive/delete/remove, family/Count↔Set transition, correction, ontology extension, conflict, unsupported op及record uncertainty always review。

Initial benchmark-only candidates：`user.office.location,user.favorite_drink,user.birth_month`。Possible later only afterheld-out validation：`pet.name,device.phone.model,desk.floor`。`vehicle.color`及`group.member_count`initial review-required。No production auto until benchmark PASS and separate enablement。

Freeze model/parameters/prompt/registry/version/risk/dataset/procedure；DeepSeek v4 Pro first；≥600 preregistered turns；unsafe=0；forbidden-risk auto=0；slot/operand/protocol errors each≤1%；review≤35%；safe automation≥65%。Oracle-approved numeral-token versus exact numeral+direct-classifier granularity alone is not an operand/value error；wrong number/slot/entity/shape/canonical value、unrelated/over-broad/missing-meaning literal及wrong authoritative result仍是error。Unsafe means any wrong slot/entity/target/operand/value/span/op/semantic claim shape/typed result/authoritative result；unsafe definition與threshold不變。

> After the frozen ontology/risk benchmark, if ANY unsafe auto-commit occurs, any forbidden-risk write auto-commits, or at least 65% safe automatic completion cannot be achieved without weakening safety rules, the project MUST STOP pursuing automatic semantic memory and retain only Human-Reviewed Memory mode. The held-out dataset and thresholds MUST NOT be changed, thresholds relaxed, or ad-hoc prompt exceptions added after results are observed. A materially new architecture or model requires a separately approved evaluation.

## 5. State-Type Model

| Type | Canonical representation | Operations | DeepSeek 決定 | App 確定性工作 | History / Proposal / Validation / Safe degrade | Migration / Cases |
|---|---|---|---|---|---|---|
| `ST-SCALAR` | `{"value": JSON scalar}`；string `<=160` chars；stable ID；descriptive semantic_key | CREATE_SCALAR, SET_VALUE, REASSERT_NOOP, DELETE_MEMORY | slot、ID、值、intent | type/equality、replace/no-op | every changed result→semantic Proposal；REASSERT_NOOP bypass；delete另標destructive | legacy 不猜 key；#1,#2,#7,#8,#11,#12,#15,#19 |
| `ST-SET` | `{"items":[canonical scalar...]}`；`<=50` items、每item `<=160` chars | CREATE_SET, ADD_ITEM, REMOVE_ITEM, REPLACE_SET, DELETE_MEMORY | collection、ID、item/complete set、evidence | membership、duplicate、set transition、empty `[]` | every changed result→semantic Proposal；remove/delete另標destructive；模糊只Clarify | legacy roster不解析；#3–#6,#13,#14,#16–#18 |
| `ST-COUNT` | `{"value": integer}`，`0..1,000,000,000` | CREATE_COUNT, SET_COUNT, INCREMENT, DECREMENT, DELETE_MEMORY | aggregate、ID、明示值或admissible delta evidence | integer/range、運算、no-op | changed result→semantic Proposal；anonymous leave禁止delta/proposal；delete另標destructive | legacy number不抽取；#9,#10,#20 |
| `ST-RECORD` | `{"fields":{...}}`；`<=20` fields、name `<=80` chars、scalar value `<=160` chars | CREATE_RECORD, SET_FIELD, DELETE_FIELD, DELETE_MEMORY | record、field、value、intent | field patch/delete、siblings preservation、final `{}` | SET_FIELD/DELETE_FIELD/DELETE_MEMORY changed result均Proposal；delete另標destructive | legacy prose不拆fields；SX-22–25 |
| `ST-RELATION` | 本原型不另建 authoritative edge；以 typed `ST-SET` membership 表示 | ADD_RELATION/REMOVE_RELATION 映射 ADD_ITEM/REMOVE_ITEM | subject/predicate/object 與 collection ID | 在同一 set lineage 執行 membership op | changed add/remove均Proposal；remove另標destructive；ambiguous object→clarify | 避免 set/edge 雙重權威；#5,#6,#17,#18 |
| `ST-PENDING` | purpose + destructive flag + immutable identity + target/create semantics + state_type + operation + typed arguments/result + base_revision | PROPOSE, CONFIRM, CORRECT, CANCEL | 形成 concrete executable mutation | deterministic create/render/scope/revision/revalidation/local apply | 非Current；Confirm archive/commit；Cancel no revision；stale/mismatch fail closed | legacy proposal保持legacy executor；SC-01–SC-20 |
| `ST-HISTORY` | full typed predecessor snapshot；legacy 保留 content | ARCHIVE/READ/DELETE_LINEAGE | read relevance IDs | exact archive/fetch/render/limit | same lineage；empty set 可保存；DELETE lineage 同刪 | additive fields；#2,#5,#8,#14,#17–#20 |

`ST-RELATION` 選 B：暫留在 typed Set membership。1–2 user 原型若同時有 relation table 與 set roster，會製造雙重權威、同步與 migration 成本；現有核准案例只需 membership 隔離。未來只有出現非集合型 predicate/query 需求時，才另案提 first-class relation。

## 6. Mutation Algebra

有限 algebra 如下；每個 operation 都只接受既定 state type 與 typed arguments：

| Family | Operations | Canonical transition |
|---|---|---|
| Scalar | CREATE_SCALAR, SET_VALUE, REASSERT_NOOP, DELETE_MEMORY | absent→v；v→v2；v=v→0；explicit forget→delete lineage |
| Set | CREATE_SET, ADD_ITEM, REMOVE_ITEM, REPLACE_SET, DELETE_MEMORY | Confirm後absent→S／S→S∪{x}／S→S−{x}／S→S2／forget→delete |
| Count | CREATE_COUNT, SET_COUNT, INCREMENT, DECREMENT, DELETE_MEMORY | absent→n；n→m；n±k（只限 admitted evidence）；forget→delete |
| Record | CREATE_RECORD, SET_FIELD, DELETE_FIELD, DELETE_MEMORY | Confirm後absent→R／`R[f]→v`／`R−{f}`（final field→`{}`）／delete lineage |
| Relation | ADD_RELATION, REMOVE_RELATION | 映射到target set membership；changed result先Proposal，Confirm後apply |
| Control | NOOP, CLARIFY, PROPOSE, CONFIRM, CANCEL, ABSTAIN, TARGET_NOT_FOUND | 不直接混入 state mutation；依狀態機執行 |

共同規則（`POLICY-06`–`POLICY-09`與`POLICY-18`–`POLICY-21`）：每user最多20筆Current；typed limits超限fail closed。每回合基於revision snapshot；same canonical value為NOOP。Changed candidate先經Risk Engine；auto route或review Confirm實際改變Current才archive/revision+1。Destructive永遠review；read/clarify/proposal/cancel/NOOP/失敗不增revision。

## 7. Deterministic vs Model-Semantic Boundary

| Concern | DeepSeek（model-semantic） | Application（deterministic） |
|---|---|---|
| Natural language | 理解 intent、entity、slot、collection、field | 不做 regex/copula/name/substring heuristics |
| Target | 從供應 snapshot 選 exact `memory_id` | 驗證存在、user ownership、state_type、revision |
| Operation | 選 semantic action、arguments 與核准 reduced basis | compiler 推導 exact canonical operation/evidence/internal kind；validator 驗 operation/type matrix 與 policy gate |
| Set | 選 target/item、辨識 addition/removal/replace | 驗證 item presence/absence、duplicate，計算結果與 `[]` |
| Count | 選 aggregate、明示 value；判斷 evidence | 驗證 integer/range；禁止 anonymous-event delta；合法時運算 |
| Record | 選 record、field、value | patch/delete exact field，保留 siblings |
| Relation | 選 subject/predicate/object 與 target set | 只變更指定 membership；不跨 collection |
| Risk/Proposal | 表達concrete semantic changed candidate；不選risk、`PROPOSE`或commit | application Risk Engine routes；review才建Proposal並binding；auto短atomic commit |
| Clarification | 說明 missing semantic slot、candidate context與question；判斷 continuation | 產生/保存 clarification ID、session-scoped context、允許欄位、expiry/revision；不自動推論答案 |
| Read | 選 memory/history IDs 或 unknown/freeform | 驗證 route/IDs；從 SQLite 確定性 render；mutation count 0 |
| Persistence | 無權直接寫 DB | stable ID、history、revision、limits、atomic commit/rollback |

Typed state 不會讓 semantic target selection 變 deterministic；wrong-but-valid ID 仍是 model risk。它只把「選定目標之後的 state transition」從 prose rewrite 轉成可驗證的 deterministic operation。

## 8. Current Schema Gaps

18個runtime gaps：

1. `memories.content` 是唯一 authoritative payload，沒有 typed canonical state。
2. generic ADD/UPDATE/DELETE 要求 provider 重寫整段內容，沒有 finite semantic delta。
3. validator 無法驗證 operation 是否適用於 state type。
4. 沒有 typed target metadata；`semantic_key`／state type 缺席。
5. Prompt 仍容許 anonymous count 事件做 4→3。
6. validator 不含 count evidence/provenance policy，格式合法的 direct/proposal 4→3 會通過。
7. explicit destructive set removal 仍可 direct UPDATE。
8. proposal schema 只能存 generic op/content，不能保存 typed arguments。
9. clarification 只留在 recent prose，沒有 lifecycle、missing evidence、scope/expiry。
10. Prompt 將 final-member removal 導向詢問表示法，沒有 canonical empty set。
11. History 只封存 prose，不能保留 typed predecessor/empty set/record fields。
12. mixed typed/legacy read/render 與 `answer.mode=freeform` bypass 尚無設計。
13. 沒有安全的 legacy gradual-conversion、duplicate-slot conflict 與 rollback schema。
14. Generic direct `DELETE` 仍可提交，沒有對 Scalar/Set/Count/Record whole-memory DELETE 強制 Proposal→Confirm。
15. Runtime沒有 POLICY-06 typed-state shape/field/item/range/4096-byte limits及一致的fail-closed validator。
16. Non-destructive model-derived changed results仍可`MUTATE` direct commit，違反`POLICY-18`。
17. Proposal storage沒有獨立`purpose`與`destructive`欄位，無法無歧義持久化unified semantic-confirmation meaning。
18. Proposal lifecycle沒有immutable payload/version identity、render/commit identity check、structured Correct新identity與production/test auto-confirm separation。

## 9. Target Schema Proposal

採最小 additive vNext，而非重建資料庫：

```text
memories:
  memory_id, user_id, position,
  state_type NULL, semantic_key NULL, state_json NULL,
  display_label NULL, schema_version NULL,
  content NULL/legacy, created_at, updated_at

memory_history:
  history_id, user_id, memory_id,
  state_type NULL, semantic_key NULL, state_json NULL,
  display_label NULL, schema_version NULL,
  content NULL/legacy, replaced_at

pending_memory_proposals:
  existing identity/scope/base_revision,
  purpose NULL, destructive NULL, payload_version NULL,
  semantic_key NULL, display_label NULL,
  state_type NULL, operation NULL, arguments_json NULL,
  legacy op/memory_id/content retained during transition,
  display_text, created_at

memory_clarifications:
  clarification_id, user_id, session_id, base_revision,
  state_type, operation, target_memory_id NULL,
  known_arguments_json, missing_fields_json,
  created_at, expires_at/status
```

Typed row invariant：`state_type/state_json/schema_version` 必須成組存在且通過 canonical JSON schema；legacy row 以 `state_type IS NULL` + nonempty `content` 表示。`memory_id` 仍是唯一 authoritative lineage identity。`state_json` 是 typed row 的權威值；不得同時把可變 `content` 當第二權威。每 user 20 current memories、history 10、既有限制與 ownership FK 維持。

Schema direction decision：**DB schema change required = YES；next version is additive v6.** Add nullable `slot_id TEXT`,`registry_version TEXT`,`entity_id TEXT` to applicable Current/History/Proposal canonical identity while retaining required proposal lifecycle fields。Legacy rows remain readable and nullable；no guessed backfill、no old-key reinterpretation、no duplicate canonical payload blob。

Typed CREATE在proposal creation時由application配置final、不可回收的stable `memory_id`並寫既有`memory_id`欄；`target_memory_id=NULL`，且exact `state_type,operation,arguments_json,semantic_key,display_label`全部持久化。此時Current/History/revision不變。Existing-target mutation以`target_memory_id`為唯一authoritative target；`semantic_key/display_label`若commit不修改可NULL且不得成為第二identity。`display_text/content`不得替代canonical fields。Confirm只從persisted payload與transaction-time Current重建；不得再生ID/key/label/arguments或重讀prose。Structured Correct建立new proposal_id/new payload；舊CREATE ID不回收。Migration不得修改Current/History或猜legacy meaning。

## 10. semantic_key Identity Strategy

評估：A（模型發字串 key）容易重新引入自然語言 equality；B（app 建 opaque slot ID）與 `memory_id` 重複且模型仍需選 target；D（獨立 registry）對 1–2 user 原型過重。推薦 **C 的受限版本**：

- `memory_id` 永遠是唯一 authoritative lineage identity。
- `semantic_key` 只是 immutable、descriptive routing metadata，不是 merge/update/delete key。
- CREATE 時 DeepSeek 可提供受 schema 限制的 descriptive key；application 只驗證格式，不宣稱理解其語意，並產生 `memory_id`。
- UPDATE/DELETE/READ 必須用 exact existing `memory_id`；禁止因 key/content/value 相同自動合併。
- 同 user 出現疑似相同 key 的多筆 typed row 時，fail closed／clarify；不得以字串 equality 自動選 lineage。
- 未來若需要真正 slot registry，須另案建立 app-issued opaque slot identity；本階段不需要。

## 11. display_text Strategy

推薦 **B：typed state 的顯示文字由 canonical state 確定性 render**；`display_label` 只作 immutable/controlled 人類可讀標籤，不是權威值。`ST-SCALAR` render label+value；`ST-SET` render label+canonical items，empty 明確為 `[]`／核准 UI 文案；`ST-COUNT` render label+integer；`ST-RECORD` 依固定 field order render；relation 由 set render；History 使用被封存 typed snapshot 同一 renderer；Proposal display_text 由 operation+arguments+stored label 產生，不信任 model prose。

Legacy row 的 `content` 在轉換前仍是該 legacy lineage 的 authoritative display。混合讀取可以同時 render typed row 與原樣呈現 legacy content，但不得從 legacy display 反推 identity。若保留 `display_text` 欄位，只能是可重建 cache 或 legacy compatibility，不能與 `state_json` 同時成為權威。

## 12. Historical Structured DeepSeek Protocol vNext — Model-Facing Boundary Superseded

下列固定13-key內容保留為原始六階段計畫的歷史記錄，**不再是未來model-facing target**。`POLICY-10`–`POLICY-14`的Semantic IR v1簡化設計又由`POLICY-15`–`POLICY-17`的Architecture D v2取代作未來target：模型輸出Grounded Claim-Shape Semantic IR v2，經structural validator、exact grounding validator與claim-shape compiler後建立下游existing canonical internal representation。Semantic IR v1與舊protocol只能作人工deployment/configuration rollback path，不得automatic retry/fallback、同turn第二次DeepSeek call或silent semantic repair。

概念性 compact discriminated JSON：

```json
{
  "reply": "ordinary reply or clarification wording",
  "decision": {
    "kind": "FREEFORM|READ|MUTATE|PROPOSE|CLARIFY|NOOP|ABSTAIN|TARGET_NOT_FOUND",
    "state_type": "scalar|set|count|record|null",
    "memory_id": "existing-id-or-null",
    "operation": "CREATE_SCALAR|SET_VALUE|ADD_ITEM|REMOVE_ITEM|SET_COUNT|SET_FIELD|...|null",
    "arguments": {},
    "evidence": "EXPLICIT_ASSERTION|EXPLICIT_TARGET_ITEM|CONTINUATION|INSUFFICIENT|...",
    "current_memory_ids": [],
    "history_ids": [],
    "unknown": false,
    "clarification": null
  }
}
```

此歷史 contract 的 behavioral restrictions 仍保留於 internal protocol：CREATE ID由app產生、READ與mutation不混合、clarification不形成 executable proposal、destructive operations必須Proposal、anonymous count event不得形成arithmetic mutation。不同處是模型不再輸出 exact `MUTATE/PROPOSE`、canonical operation/evidence或固定 irrelevant fields；compiler依有效 Semantic IR確定性建立它們。

## 13. Validation Layer vNext

完整 app-side validation 分兩層：先驗證 discriminated Semantic IR，再驗證 compiler 產生的 existing canonical internal decision。Compiler 不得查看原始自然語言或修復 semantic fields。

- exact JSON shape、discriminator、欄位型別、大小、operation count；不接受額外欄位。
- operation 只能出現在允許的 state type；CREATE 無 target，非 CREATE 必須有 exact target。
- target exists、屬於 user、state type 一致；history/read IDs scope 正確且不重複。
- semantic_key 僅格式驗證，不用於 identity；新 typed record 不可造成已知 exact registry collision，疑義 fail closed。
- Set items 型別與 canonical uniqueness；ADD 要 item 不存在；REMOVE 要存在；REPLACE 必須 complete；empty set 保持同 lineage。
- Count 必須integer（禁止bool）且 `0..1,000,000,000`；SET_COUNT要explicit asserted value；INCREMENT/DECREMENT要admitted evidence；anonymous member event一律拒絕executable delta/proposal。
- Scalar string `<=160` chars；Set `<=50` items且每item `<=160` chars；Record `<=20` fields、field name `<=80` chars、scalar value `<=160` chars；serialized typed state `<=4096` UTF-8 bytes；超限fail closed、不截斷。
- Record field key需schema；SET_FIELD需exact field/value且保留siblings；DELETE_FIELD需exact existing field、必須PROPOSE、保留same `memory_id`，final field後為`{}`；不得等同DELETE_MEMORY。
- destructive collection membership、DELETE_FIELD與所有Scalar/Set/Count/Record whole-memory DELETE由application policy推導PROPOSE；target/result不完整只能接受model明示且合約有效的CLARIFY，或fail closed；nonexistent field為deterministic TARGET_NOT_FOUND/safe abstention。
- proposal user/session/base revision、typed op/args、target snapshot與 Confirm 時重驗；active proposal uniqueness。
- clarification user/session/base revision、missing fields、continuation binding、expiry；不能當 Current/Pending。
- reassert canonical equality→NOOP，無 History、無 revision。
- revision guard、同回合 operation conflict、20 current limit、typed state serialized-size limits、legacy 160-char compatibility、history 10、reply/input/token limits。
- firewall 對任何 MUTATE/PROPOSE 一體適用；invalid/DB error 全回合 rollback。

## 14. Proposal Model vNext

現schema可保存typed operation/arguments，但不足以安全表示`POLICY-18/19`：沒有distinct purpose、destructive flag、payload version或CREATE semantic_key/display_label；generic `UPDATE content`亦無法讓Confirm重驗完整semantic operands。

Human Review semantic proposal保存normalized identity，包括`proposal_id,user_id,session_id,base_revision,purpose,destructive,payload_version,memory_id,state_type,operation,target_memory_id,arguments_json`及registry-derived `slot_id,registry_version,entity_id,semantic_key,display_label`。CREATE配置final memory_id；Confirm exact revalidation且不重建payload。只有Risk Engine=`HUMAN_REVIEW_REQUIRED`走此模型；auto route不建立proposal。Legacy只由legacy executor完成。

Confirm與Cancel各0 provider calls。Structured local Correct若supported，建立new immutable proposal identity/version；natural-language correction是新semantic turn。Production auto-confirm禁止。Test-only runner只在dedicated safe test DB且complete oracle exact match後呼叫Confirm；mismatch在Confirm前FAIL。

## 15. Clarification State Model

Pending Proposal 表示「已存在 exact executable mutation，只等授權」；Clarification 表示「必要證據不足，尚無 executable mutation」，兩者不能共用狀態。

最小 clarification row：`clarification_id,user_id,session_id,base_revision,state_type,operation,target_memory_id?,known_arguments_json,missing_fields_json,created_at,expires_at/status`。它不是 long-term memory，不增加 revision，不阻擋無關新 intent，不可由 Confirm/Cancel endpoint 執行。下一回合 DeepSeek 只需表達 `CONTINUATION` 與補足允許的 missing semantic field；application 自行綁定 live clarification ID 並驗 scope/revision/expiry/shape。模型不產生或回傳 clarification ID。無關 request 應正常處理且 clarification 被明確保留為 inert 或安全關閉；兩種策略都必須確保不能消費生日、desk 等無關值。

Case #14 lifecycle：`remove one` → app 儲存缺 item 的 Clarification（0 mutation、0 proposal）→ `Eva` 由application綁定該 clarification → DeepSeek 回 semantic `state_type=set, action=remove, target_id=Project Alpha, item=Eva, basis=ASSERTION` → compiler derives exact `REMOVE_ITEM + EXPLICIT_TARGET_ITEM + PROPOSE` → app 建 concrete Proposal（0 mutation）→ local Confirm → deterministic set becomes `[Frank]`、archive `[Eva,Frank]`、revision +1、proposal/clarification consumed。不得在 `Eva` 回合 direct commit。

## 16. Historical State Model

選 **B：History 封存完整 typed predecessor state**，不是只存 rendered content。至少保存 `memory_id,state_type,semantic_key,state_json,display_label,schema_version,replaced_at`；legacy predecessor 仍保存原 `content`。這能精確保存 scalar predecessor、set membership、record siblings、count value、explicit empty set與DELETE_FIELD前的完整record，並由同一 renderer 支援自然語言 historical reads。

UPDATE只在canonical state實際改變時archive；reassert不新增row；每user保留最近10筆政策不變。DELETE_MEMORY移除current與同lineage history；REMOVE_ITEM到`[]`與DELETE_FIELD到`{}`都是same-lineage UPDATE，Confirm後必須archive完整非空predecessor並保留current lineage。

## 17. Read Path Model

DeepSeek 仍負責 semantic READ routing、current/history IDs 或 unknown selection；model-facing IR 不需固定13-key shape。Compiler derives internal READ、`READ_SELECTION`與empty/default fields；app驗證IDs後fetch SQLite，typed rows deterministic render、legacy rows exact content render，並分別標示Current/History。沒有 relevant committed record時使用固定unknown。所有read canonical mutation count為0，不建立proposal、不消費clarification、不改revision/history。Wrong-but-valid ID風險仍屬model-semantic。

`answer.mode=freeform` bypass：typed state只 **PARTIALLY** 解決。它讓已選 typed record 的值與 render 可確定，但不能保證模型一定將個人查詢路由成 READ，也不能識別 wrong-but-valid relevant ID。vNext 必須保留 mutual-exclusion validation、禁止 freeform 攜帶 memory refs／mutation；個人查詢錯誤路由仍是 model-semantic limitation，可在未來以更嚴格的 protocol/prompt與 contract tests降低風險，但不可宣稱 deterministic。長 Session 仍只送六回合／12,000字 recent context，而 long-term snapshot 按 user 供應。

## 18. Legacy Migration Strategy

選 **D：hybrid gradual migration**（本質結合 A，拒絕 B/C 的批次猜測）：

1. additive schema migration，所有既有 row 標為 legacy；Current、History、Proposal、revision、user ownership 原樣保留。
2. 新建立、具明確 typed decision 的 facts 使用 typed row。
3. legacy lineage 只在使用者明確更新、模型提供 exact existing ID + typed target/op，且 app 可驗完整形狀時轉換；破壞性動作照 Proposal policy。
4. 轉換保留相同 `memory_id`，先把完整 legacy predecessor 封存，再寫 typed current。
5. 不做 DeepSeek bulk migration、不用 regex/local heuristic、不從任意 prose 猜 set/count/record。
6. mixed duplicate slot 或不確定映射一律 fail closed/clarify；未來可另做 user-initiated review，不在自動 migration。

Option A 最安全但長期會留下全部 legacy；B 有 API 成本且模型遷移錯誤會永久化；C 違反禁止 heuristic identity；D 能逐步取得 deterministic guarantees 並維持 rollback。

## 19. Backward Compatibility

Reader 按 row discriminator dual-read：typed→schema validate+deterministic render；legacy→exact content。Writer 不得用 typed operation 修改 legacy payload，除非走明確 conversion transaction。History reader同理。Legacy proposal只能使用舊 op/content executor；typed proposal只能用 operation/arguments executor。

同一 user 同時有 typed 與 legacy records 時，兩者都保留 stable ID 與權威性。若模型認為可能代表同一 slot，不能以 semantic_key/prose/value合併；應 CLARIFY 或 TARGET_NOT_FOUND/fail closed。新 CREATE 若與 supplied snapshot 中疑似既有 lineage 衝突，模型應選 existing ID；app僅能拒絕 exact registry collision，不能做 semantic matching。Rollback 可讓新 binary繼續讀 legacy欄位；若 typed writes 已發生，回滾前需 schema-aware export/restore，不能直接降版遺失 typed資料。

## 20. POLICY-01 Gap

核准行為：count=4 + anonymous member leaves → mutation 0、無 executable Proposal，後續 read仍為4。

- System Prompt conflict：明寫 deterministic relative changes，且以 `count 4 + one member left = 3` 為正例；另明寫 count-only memory 可安全變3。
- Validator gap：只驗 generic UPDATE/proposal 的 ID/content/schema，沒有 evidence class、state type或 anonymous-event prohibition；direct 4→3與proposal 4→3皆可通過。
- Proposal gap：anonymous event 可形成 concrete generic UPDATE proposal，違反 `INV-19`。
- Test conflict：test 05 接受 proposal；test 18 接受 direct UPDATE；另 test 06/09/10/16 以相同不合法語意作 proposal mechanics fixture。
- Read implication：若錯誤 direct/Confirm 已提交，SQLite exact render會忠實呈現錯誤3；deterministic render不能修復錯誤 commit。未提交時 test 04 的 later read=4 是正確的。
- Required future change：移除 Prompt正例；vNext count op要求 `EXPLICIT_ASSERTED_COUNT` 或核准 delta evidence；validator拒絕 anonymous membership `DECREMENT` 與 proposal；回覆 CLARIFY/ABSTAIN且不留會污染後續 read 的 executable state；重寫衝突測試，強化 Cases #9/#10/#20。

## 21. POLICY-02 Gap

核准行為：exact destructive named collection removal 必須 concrete Proposal→local Confirm/Cancel；ambiguous removal只 clarification、無 Proposal。

現 runtime允許 DeepSeek直接回 generic UPDATE，test 02 也直接把 Research `Alice,Bob,Carol` 改成 `Alice,Carol`。validator不知道這是 destructive membership removal，因此無法強制 proposal。proposal payload又只有 final content，不能重驗 exact member operation。

未來typed Set membership writes初始均`HUMAN_REVIEW_REQUIRED`；`REMOVE_ITEM`永遠destructive review。建立proposal時驗target/item/result；ambiguous input→CLARIFY，duplicate-add→NOOP。不得direct unreviewed commit。

## 22. POLICY-03 Gap

核准行為：`[Alice] -> []` 是同 stable lineage UPDATE，不是 DELETE。現 SQLite `content` 技術上可存某段「空名冊」文字，但沒有 canonical empty set；validator無法證明其為 empty、renderer無固定表示、Prompt反而要求詢問如何表示並 NOOP，test 04 final-member subcase也固定該舊行為。History只能存 prose，不能結構化證明 predecessor。

未來 typed set 的 `state_json={"items":[]}` 必須合法；REMOVE_ITEM deterministic 得到 `[]`；proposal預覽與Confirm保留 memory_id，archive `[Alice]` typed predecessor；render使用固定空集合格式；memory count仍為一筆 current lineage；只有 explicit forget collection才 DELETE lineage。更新 schema、validator、Prompt、proposal、history、renderer與既有 test 04（維持總數20，以 contract-class test取代舊assertion）。

## 23. POLICY-04 Implications

治理已權威化，但下列非治理資產仍有 stale assumptions，後續 implementation task才可修改：

- `app.py` SYSTEM_PROMPT：anonymous count arithmetic、direct exact named-set update、final-member「詢問表示法」三項過時。
- `test_app.py`：test 02 direct destructive set；test 04 final-member clarification；test 05/18 count 4→3；test 06/09/10/16 使用 anonymous count proposal fixture。
- `README.txt`：描述 undefined empty-collection representation要 clarification，未描述 typed state與 POLICY-01/02/03。
- `TEST_RESULTS.txt`：仍把 count 4→proposal 3/Confirm與 direct named-set removal列為 PASS；這是 pre-policy歷史結果，不能代表 current approved behavior。
- Prompt comments：runtime Prompt 本身是 stale policy text；未發現另有 production code comment聲稱 anonymous count或final-empty舊政策。
- Tests/code comments：migration與transaction註解未形成政策衝突；問題在測試資料與 assertions，而非一般 code comments。

## 24. 20 Acceptance Case Gap Matrix

| Case | Current runtime | Target runtime | Gap | Type / op | Proposal? / Clarify? | History | Deterministic app work | Model dependency | Test change / Manual |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | Partial | Typed pass | free-text slot | Scalar / CREATE, READ | **Y if changed**/N | none until Confirm | create/render/proposal | slot/value/read IDs | contract test / Y |
| 2 | Partial | Typed pass | canonical scalar absent | Scalar / SET_VALUE | **Y if changed**/N | same-ID predecessor on Confirm | equality/archive/render | target/new value | contract test / Y |
| 3 | Prompt-only/optional | Typed admitted or abstain | no set algebra | Set / CREATE_SET, READ | **Y if changed**/N | none until Confirm | uniqueness/count/list/proposal | complete roster | add coverage / Y |
| 4 | Partial | Typed isolation | model rewrites sets | Set / CREATE_SET | **Y if changed**/N | none until Confirm | distinct IDs/sets/proposal | correct collection | add coverage / Y |
| 5 | Conflicting direct path | Proposal flow | no remove gate | Set / REMOVE_ITEM | **Y**/if ambiguous | target predecessor | membership/result/scope | target+item | replace test02 / Y |
| 6 | Prompt/model rewrite | Typed add | no duplicate-item check | Set / ADD_ITEM | **Y if changed**/if ambiguous | set predecessor on Confirm | presence/union | target+item | add coverage / Y |
| 7 | Partial | Typed pass | free-text slot | Scalar / CREATE, READ | **Y if changed**/N | none until Confirm | create/render/proposal | slot/value | contract test / Y |
| 8 | Partial | Typed pass | canonical field absent | Scalar / SET_VALUE | **Y if changed**/N | same-ID predecessor on Confirm | replace/archive | target/value | contract test / Y |
| 9 | Partial | Typed admitted or abstain | count embedded string | Count / CREATE_COUNT, READ | **Y if changed**/N | none until Confirm | integer/render/proposal | asserted aggregate | add coverage / Y |
| 10 | **Conflicting** | 0 mutation | Prompt/validator/proposal permit 4→3 | Count / CLARIFY, ABSTAIN | **N**/Y | unchanged | policy reject/read4 | detect anonymous event/evidence | replace tests05/18 / Y |
| 11 | Partial | Typed isolation | clarification only prose | Scalar / CREATE, READ | **Y if changed**/N | none until Confirm | ignore inert clarification/proposal | new intent/slot | continuation test / Y |
| 12 | Partial | Typed pass | routing model-only | Read+Scalar / UNKNOWN, CREATE | **Y for CREATE**/N | none until Confirm | fixed unknown/create/render | route/slot | contract test / Y |
| 13 | Prompt-only | Typed clarification | no scoped clarification state | Set+Scalar / CLARIFY, CREATE | N/Y first | unchanged | bind/isolate state | unrelated-intent decision | add coverage / Y |
| 14 | Unsupported lifecycle | Clarify→Proposal→Confirm | no clarification token | Set/Pending / REMOVE_ITEM | **Y after continuation**/Y first | predecessor on Confirm | state machine/remove | continuation+item | add coverage / Y |
| 15 | Partial | Typed isolation | textual stale context | Scalar/Pending / CREATE, READ | **Y for CREATE**/N | none until Confirm | expiry/scope/proposal | new intent | add coverage / Y |
| 16 | Partial | Typed mixed pass | sets free-text | Set+Scalar / CREATE, READ | **Y if changed**/N | none until Confirm | per-ID isolation/proposal | slot/collection selection | add coverage / Y |
| 17 | Conflicting direct allowed | Proposal typed | no mandatory remove proposal | Set/History / REMOVE_ITEM, CREATE | **Y**/if ambiguous | Team predecessor | remove/archive/isolate | targets/read IDs | add coverage / Y |
| 18 | Conflicting direct allowed | Proposal typed | relation implicit/proposal ungated | Set/Relation / REMOVE_ITEM | **Y**/if ambiguous | Photo predecessor only | exact set transition | target relation | add coverage / Y |
| 19 | Partial | Deterministic NOOP | semantic equality not typed | Scalar / REASSERT_NOOP | N/N | unchanged | canonical equality | target/value selection | add coverage / Y |
| 20 | Partial | Typed+legacy reads, 0 ops | route/ref limit/stale prose | Read / READ_* | N/N | unchanged | validate/render/no-write | relevance/route | long-session test / Y |

## 25. 68 Semantic Contract Gap Matrix

下表前51列保留Part 1之前的runtime baseline分類：`FULLY IMPLEMENTED 7`、`PARTIALLY IMPLEMENTED 29`、`PROMPT-ONLY 7`、`UNSUPPORTED 6`、`CONFLICTING 2`。Architecture D新增9份contract及Semantic Confirmation新增8份contract，使approved total為68；新增17份的current runtime皆尚未完整實作，closure列於表後。`SAFE-DEGRADE ONLY` 與 `TEST GAP` 沒有作為 primary runtime classification；其測試缺口另列第 27 節。

| # | Contract | Current classification | 核心理由／target closure |
|---:|---|---|---|
| 1 | MSC-SCALAR-CREATE | PARTIALLY IMPLEMENTED | ADD/limits可執行；slot identity無typed key |
| 2 | MSC-SCALAR-READ | PARTIALLY IMPLEMENTED | selected ID exact render；route/ID語意依模型 |
| 3 | MSC-SCALAR-REPLACE | PARTIALLY IMPLEMENTED | stable ID/history完整；target/value不透明 |
| 4 | MSC-SCALAR-REASSERT | PARTIALLY IMPLEMENTED | exact-string no-op；canonical equality不保證 |
| 5 | MSC-SCALAR-DELETE | PARTIALLY IMPLEMENTED | scoped lineage delete；semantic target依模型 |
| 6 | MSC-SET-CREATE | PARTIALLY IMPLEMENTED | 可存 roster prose；無item schema |
| 7 | MSC-SET-READ | PARTIALLY IMPLEMENTED | exact prose render；無deterministic list/count |
| 8 | MSC-SET-ADD-ITEM | PROMPT-ONLY | Prompt要求正確rewrite；app不驗membership |
| 9 | MSC-SET-REMOVE-ITEM | CONFLICTING | direct UPDATE可通過，違反mandatory Proposal/empty set |
| 10 | MSC-SET-REPLACE | PROMPT-ONLY | complete replacement只有模型判斷 |
| 11 | MSC-SET-AMBIGUOUS-MUTATION | PROMPT-ONLY | 無typed ambiguity/clarification gate |
| 12 | MSC-SET-CROSS-COLLECTION-ISOLATION | PARTIALLY IMPLEMENTED | delta隔離但wrong valid ID不可辨 |
| 13 | MSC-SET-DUPLICATE-MEMBERSHIP | PROMPT-ONLY | only whole-content duplicate，無item check |
| 14 | MSC-COUNT-CREATE | PARTIALLY IMPLEMENTED | 可存prose，無integer typed validation |
| 15 | MSC-COUNT-READ | PARTIALLY IMPLEMENTED | selected prose exact；numeric field不透明 |
| 16 | MSC-COUNT-EXPLICIT-SET | PROMPT-ONLY | explicitness/value only由模型決定 |
| 17 | MSC-COUNT-DERIVED-DELTA | CONFLICTING | Prompt/tests允許anonymous 4→3 |
| 18 | MSC-RECORD-SET-FIELD | UNSUPPORTED | 無record/field operation |
| 19 | MSC-RECORD-DELETE-FIELD | UNSUPPORTED | generic DELETE無法區分field |
| 20 | MSC-RECORD-DELETE-RECORD | UNSUPPORTED | generic lineage近似但無record boundary |
| 21 | MSC-RELATION-ADD | UNSUPPORTED | 只有free-text set rewrite |
| 22 | MSC-RELATION-REMOVE | UNSUPPORTED | 無edge identity，且destructive gate缺失 |
| 23 | MSC-PENDING-CREATE | PARTIALLY IMPLEMENTED | scope/schema完整；typed op與政策gate不足 |
| 24 | MSC-PENDING-CONFIRM | FULLY IMPLEMENTED | local、scope、revision、atomic apply |
| 25 | MSC-PENDING-CANCEL | FULLY IMPLEMENTED | local remove、no memory/revision change |
| 26 | MSC-PENDING-AMBIGUOUS-NO-PROPOSAL | PROMPT-ONLY | app不能判定guessed proposal |
| 27 | MSC-PENDING-CONTINUATION | UNSUPPORTED | 無clarification state/token |
| 28 | MSC-PENDING-STALE-ISOLATION | PARTIALLY IMPLEMENTED | stored proposal強；text clarification弱 |
| 29 | MSC-PENDING-UNRELATED-REQUEST | PARTIALLY IMPLEMENTED | active proposal阻擋；純澄清無隔離模型 |
| 30 | MSC-HISTORY-PREDECESSOR | FULLY IMPLEMENTED | valid UPDATE同ID archive/limit/transaction |
| 31 | MSC-HISTORY-CURRENT-VS-PAST | PARTIALLY IMPLEMENTED | render分層；selection依模型 |
| 32 | MSC-HISTORY-REASSERT-PRESERVATION | PARTIALLY IMPLEMENTED | exact-string有效；semantic equality不保證 |
| 33 | MSC-HISTORY-DELETE-LINEAGE | PARTIALLY IMPLEMENTED | scoped delete current+linked history已實作；whole-memory mandatory Proposal gate缺失 |
| 34 | MSC-READ-CURRENT | PARTIALLY IMPLEMENTED | exact selected values；routing/relevance依模型 |
| 35 | MSC-READ-HISTORY | PARTIALLY IMPLEMENTED | exact selected history；relevance依模型 |
| 36 | MSC-READ-UNKNOWN | PARTIALLY IMPLEMENTED | fixed reply；unknown routing依模型 |
| 37 | MSC-READ-LONG-SESSION | PARTIALLY IMPLEMENTED | persistence/context limits；ref/relevance限制 |
| 38 | MSC-READ-NO-MUTATION | PARTIALLY IMPLEMENTED | mixed schema拒絕；read intent依模型 |
| 39 | MSC-READ-DETERMINISTIC-STORED-VALUE | FULLY IMPLEMENTED | valid IDs後完全SQLite render |
| 40 | MSC-ISO-USER | FULLY IMPLEMENTED | query/operation/proposal均user-scoped |
| 41 | MSC-ISO-SESSION | FULLY IMPLEMENTED | recent/proposal session-scoped，LTM user-scoped |
| 42 | MSC-ISO-COLLECTION | PARTIALLY IMPLEMENTED | untargeted ID不變；semantic collection selection不保證 |
| 43 | MSC-ISO-SLOT | PARTIALLY IMPLEMENTED | lineage isolation；semantic slot selection不保證 |
| 44 | MSC-ISO-PENDING | PARTIALLY IMPLEMENTED | stored proposals完整；clarification未typed |
| 45 | MSC-SAFE-NO-HALLUCINATION | PARTIALLY IMPLEMENTED | SQLite render/unknown強；routing可錯 |
| 46 | MSC-SAFE-NO-ARBITRARY-TARGET | PROMPT-ONLY | app只驗valid ID，不驗語意target |
| 47 | MSC-SAFE-NO-CROSS-RETRACT | PARTIALLY IMPLEMENTED | delta scope強；wrong set ID風險 |
| 48 | MSC-SAFE-NO-DUPLICATE-ACTIVE | PARTIALLY IMPLEMENTED | exact content only；semantic duplicate可能 |
| 49 | MSC-SAFE-NO-STALE-PENDING-CONTAMINATION | PARTIALLY IMPLEMENTED | revision proposal強；text clarification弱 |
| 50 | MSC-SAFE-FAIL-CLOSED | FULLY IMPLEMENTED | validation/DB failure rollback all |
| 51 | MSC-SAFE-REFERENCE-DATA | PARTIALLY IMPLEMENTED | firewall deterministic heuristic；outer intent/NLP不完備 |

Architecture D與Semantic Confirmation新增contract gap：

| # | Contract | Current classification | 核心理由／target closure |
|---:|---|---|---|
| 52 | MSC-GROUND-EXPLICIT-LITERAL | PARTIALLY IMPLEMENTED | Phase 3A model-span validator已存在；Phase 3B.1 application unique-exact literal resolver尚未實作 |
| 53 | MSC-CLAIM-CARDINALITY | UNSUPPORTED | claim-shape compiler尚未上線 |
| 54 | MSC-CLAIM-ENUMERATION | UNSUPPORTED | complete grounded enumeration compiler尚未上線 |
| 55 | MSC-CLAIM-MEMBERSHIP | UNSUPPORTED | grounded membership compiler尚未上線 |
| 56 | MSC-COUNT-SET-SINGLE-AUTHORITY | UNSUPPORTED | single-authority resolver尚未上線 |
| 57 | MSC-COUNT-TO-SET-REPRESENTATION | UNSUPPORTED | same-ID representation transition與proposal gate尚未上線 |
| 58 | MSC-SET-CARDINALITY-NOOP | UNSUPPORTED | typed deterministic equality gate尚未上線 |
| 59 | MSC-SET-CARDINALITY-CONFLICT-CLARIFY | UNSUPPORTED | conflict CLARIFY gate尚未上線 |
| 60 | MSC-GROUND-FAIL-CLOSED | UNSUPPORTED | IR v2 pre-compiler rejection尚未上線 |
| 61 | MSC-SEMANTIC-PROPOSAL-CREATE | UNSUPPORTED | review-route immutable proposal與registry metadata尚未上線 |
| 62 | MSC-SEMANTIC-PROPOSAL-CONFIRM | PARTIALLY IMPLEMENTED | local generic Confirm存在；typed payload identity與full revalidation未完成 |
| 63 | MSC-SEMANTIC-PROPOSAL-CANCEL | PARTIALLY IMPLEMENTED | local Cancel存在；new semantic payload identity尚未完成 |
| 64 | MSC-SEMANTIC-PROPOSAL-UNIFIED-DESTRUCTIVE | PARTIALLY IMPLEMENTED | destructive proposal存在；purpose/destructive分離與unified one-confirm尚未完成 |
| 65 | MSC-SEMANTIC-PROPOSAL-NOOP-BYPASS | PARTIALLY IMPLEMENTED | 部分NOOP存在；全typed family deterministic bypass未完成 |
| 66 | MSC-SEMANTIC-PROPOSAL-STALE | PARTIALLY IMPLEMENTED | base-revision stale gate存在；canonical payload identity/precondition重驗未完成 |
| 67 | MSC-SEMANTIC-PROPOSAL-CORRECT | UNSUPPORTED | structured local Correct/replacement proposal identity尚未上線 |
| 68 | MSC-SEMANTIC-PROPOSAL-COMMIT-IDENTITY | UNSUPPORTED | immutable display/commit identity與payload version尚未上線 |

## 26. Current Automated Test Audit

實跑：`python -W error::ResourceWarning -m unittest -v test_app.py`；結果 `Ran 20 tests ... OK`，即 `20/20`，且 strict ResourceWarning 模式通過。

| Test | Classification | Audit finding |
|---:|---|---|
| 01 | PARTIALLY ALIGNED | atomic add/cross-session/read正確；typed slot未覆蓋 |
| 02 | CONTRADICTS GOVERNANCE | Bob removal direct UPDATE，違反 POLICY-02 |
| 03 | CONTRADICTS GOVERNANCE | direct whole-lineage DELETE，違反 POLICY-07 mandatory Proposal |
| 04 | PARTIALLY ALIGNED | unresolved count/read4正確；final-member clarification assertion違反 POLICY-03 |
| 05 | CONTRADICTS GOVERNANCE | anonymous count形成4→3 proposal |
| 06 | PARTIALLY ALIGNED | Confirm機制正確；anonymous count fixture不合法 |
| 07 | ALIGNED WITH GOVERNANCE | proposal DELETE只刪target lineage |
| 08 | ALIGNED WITH GOVERNANCE | proposal ADD由app產生ID |
| 09 | PARTIALLY ALIGNED | Cancel機制正確；anonymous count fixture應換掉 |
| 10 | PARTIALLY ALIGNED | stale fail-closed正確；anonymous count fixture應換掉 |
| 11 | ALIGNED WITH GOVERNANCE | cross-user proposal拒絕 |
| 12 | ALIGNED WITH GOVERNANCE | cross-session pending/recent隔離 |
| 13 | IMPLEMENTATION-ONLY | clear-user與other-user隔離回歸 |
| 14 | IMPLEMENTATION-ONLY | active proposal/UI request guard；非clarification continuation |
| 15 | ALIGNED WITH GOVERNANCE | firewall原子拒絕 proposal |
| 16 | PARTIALLY ALIGNED | DB rollback正確；anonymous count fixture應換掉 |
| 17 | ALIGNED WITH GOVERNANCE | restart proposal persistence |
| 18 | CONTRADICTS GOVERNANCE | fallback接受anonymous count direct 4→3；其餘schema fail-closed正確 |
| 19 | IMPLEMENTATION-ONLY | v2→v3 migration；非typed migration |
| 20 | ALIGNED WITH GOVERNANCE | failure/stale/foreign/atomic history-message不變 |

直接政策矛盾 tests：02、03、05、18，以及 test 04 的 final-member子案例。06、09、10、16 的主要機制與治理一致，但使用了 POLICY-01 不允許形成的 proposal fixture，重組 suite 時必須換成合法 proposal情境。

## 27. Target Automated Test Design

仍維持恰好 20 個 unittest，但改成 contract-class coverage，不等同手動20案例：

1. scalar create/read/cross-session plus changed-create Proposal；2. scalar replace Proposal/stable-ID/typed history；3. scalar reassert NOOP without Proposal；4. whole-memory DELETE Proposal→Confirm/Cancel across typed families；5. set create Proposal/read/isolation；6. set changed-add Proposal/duplicate NOOP；7. explicit set remove creates destructive Proposal；8. ambiguous set remove creates Clarification only；9. final-member Confirm yields `[]`；10. POLICY-01 anonymous count nonexecution/read4；11. explicit count create/set Proposal/range；12. record SET_FIELD Proposal preserves siblings/ID/history；13. DELETE_FIELD Proposal/Confirm/Cancel、ambiguous/missing field、final `{}`且distinct from DELETE_MEMORY；14. clarification→proposal→Confirm continuation；15. unrelated request/stale clarification isolation；16. Confirm/Cancel/Correct/stale/user/session/immutable-identity proposal matrix；17. typed History/current/past/read-zero-mutation；18. firewall/schema/grounding/semantic-policy fail-closed atomicity；19. additive typed plus proposal-metadata migration/mixed typed+legacy/restart；20. DB failure/revision race/limits/UI shared guards and production-auto-confirm rejection。

主要test gaps包含registry ownership、entity identity、schema v6、Risk Engine all-condition routing、default review、unsafe metric、`OR-01`–`OR-20`，以及`SC-01`–`SC-20` Human Review lifecycle。可用parameterized subtests維持20 tests。

四層驗證不可混淆：20 automated tests驗 deterministic contract classes與mock protocol；20 approved manual acceptance cases驗端到端產品語意政策；20 semantic-confirmation cases驗proposal lifecycle與test-only oracle；42 semantic scenarios提供 state×mutation×evidence×ambiguity×history×isolation 的 traceability與擴充覆蓋。

## 28. 42-Scenario Coverage Strategy

沿用核准 `SX-01`–`SX-42`，每個 scenario 建 trace row指向 automated test、manual case、offline/live需要：

- `SX-01`–`SX-08`：scalar create/replace/reassert/delete/read、slot隔離與 history。
- `SX-09`–`SX-16`：set create/add/duplicate/remove/ambiguity/cross-set/final-empty。
- `SX-17`–`SX-21`：count create/explicit set/anonymous nonexecution/read。
- `SX-22`–`SX-25`：SET_FIELD semantic Proposal→Confirm replacement；DELETE_FIELD Proposal/Confirm與full predecessor；whole-record DELETE_MEMORY；ambiguous/missing field零變更；final `{}`增列為SX-23 subscenario。
- `SX-26`–`SX-28`：relation-as-set add/remove/ambiguous target。
- `SX-29`–`SX-34`：proposal create/confirm/cancel/stale、clarification continuation、unrelated request。
- `SX-35`–`SX-38`：typed predecessor、history/unknown/zero-mutation reads。
- `SX-39`–`SX-42`：user/session isolation、reference firewall、DB rollback。

HARD/SAFETY scenario 必須有 deterministic offline assertion；OPTIONAL scenario可回 `FEATURE_NOT_ADMITTED`，但必須驗證零 mutation與不虛構。只有自然語言 selection/continuation需要少量 live calls；mock pass不得報為real DeepSeek pass。

## 29. Implementation Phases

| Phase | Likely files | Schema / code / Prompt / tests | Migration risk / rollback | Offline verification | Live verification | Max paid calls |
|---:|---|---|---|---|---|---:|
| 1 Protocol scaffolding | app.py,test_app.py | vNext dataclasses/schema validator behind unused flag；無DB行為；contract tests重組起點 | 低；remove flag/code | strict20、invalid schema/property fixtures | none | 0 |
| 2 Additive typed schema | app.py,test_app.py | nullable typed current/history/proposal + clarification table；POLICY-06 limits；legacy untouched | 中；pre-migration backup，rollback binary仍讀legacy | migration copy、limits、restart、ownership、rollback | none | 0 |
| 3 Typed engine/render | app.py,test_app.py,index.html | scalar/set/count/record deterministic algebra；歷史計畫原稱SET_FIELD direct，現由POLICY-18 supersede為Proposal→Confirm；DELETE_FIELD final `{}`；history/render、mixed reads | 中；feature flag回legacy writer，typed export | 20 contract tests + SX deterministic subset | representative create/read | 2 |
| 4 Policy gates/protocol Prompt | app.py,test_app.py | POLICY-01–09、vNext response、typed proposal/clarification、REMOVE_ITEM/DELETE_FIELD/DELETE_MEMORY gates、revision/display rules；替換衝突tests | 中高；disable vNext and restore DB backup | Cases 5/9/10/14/17/18 mocks、field/whole-delete、NOOP/revision、firewall/failure | count nonexecution + set/field/delete proposal | 2 |
| 5 Gradual legacy/UI integration | app.py,index.html,test_app.py | explicit legacy conversion、mixed conflict、clarification UI/proposal lifecycle | 中高；no bulk conversion；per-lineage backup/history | mixed DB、session/user/UI guards、restart | legacy update + continuation | 2 |
| 6 Acceptance & release evidence | test_app.py,README.txt,TEST_RESULTS.txt（另案） | 完整20 unittest、20 manual、42 trace；更新stale docs；不改治理除非新決策 | 低；release checkpoint/DB restore drill | strict20、all deterministic matrix | final representative hard cases only | 2 |

上表六階段是 typed-engine/schema/persistence 實作歷史，不得刪除或改寫成從未存在。該架構與 `POLICY-05`–`POLICY-09` 保持核准；其中 model-facing 13-key protocol 與「模型輸出 exact op/evidence/PROPOSE/clarification ID」部分，由 boundary plan supersede。

### 29.1 Registry/Risk future implementation phases

本治理任務不得開始實作。另一個明確授權的future task MUST依序執行，不能跳phase：

1. **Slot Registry types/config**：immutable/versioned definitions、the 12 exact Registry-v1 labels、exact `semantic_key=slot_id` lookup與static validation only；不改runtime routing。Exact-label blocker已由approved narrow governance amendment resolved。
2. **Schema v6**：additive nullable `slot_id,registry_version,entity_id`於適用Current/History/Proposal；legacy readable、no guessed backfill。
3. **Constrained IR update**：known slot只選provided canonical ID或`UNKNOWN_SLOT`，entity/target只選provided candidates。
4. **Phase 3B.1 — application-derived unique exact literal resolution**：model operand輸出semantic role與non-empty exact `claimed_literal`；application在original current-turn text計算全部exact occurrences。Exactly one→`RESOLVED_EXACT`及authoritative offsets/slice；zero→`LITERAL_NOT_FOUND`；multiple→`LITERAL_AMBIGUOUS`。不得first-match、normalization、fuzzy/alias/translation、regex semantic inference、prefix/suffix repair、retry或second model。Wrong-but-exact只證明provenance。Count literal另依narrow governance可為numeral或exact numeral+direct classifier phrase，application不得解析或剝除classifier。Phase 3B.1 offline及D1–D2已完成；D3 `五位`結果reclassify為semantic PASS，D4可由human執行；D4/D5完成前及另案授權前不得Phase 4。
5. **Slot/entity compiler integration**：registry derivation、Architecture D exact grounding、family/op/evidence mapping與Architecture B preconditions。
6. **Deterministic Risk Engine**：pure classifier、all-condition auto rule、default Human Review及always-review classes。
7. **Routing**：auto path short atomic commit；review path immutable proposal/local resolution；production auto remains disabled。
8. **Offline benchmark harness**：register exact oracles、unsafe metric、threshold calculation及frozen configuration manifest。
9. **Fixed held-out benchmark**：DeepSeek v4 Pro first；至少600 preregistered auto-eligible turns；no post-result tuning。
10. **Go/no-go decision**：apply thresholds and mandatory STOP rule；only PASS may support separate production enablement authorization。
11. **Only after PASS — Real40 / broader product tests**：preserve R05/R21 review policy unless separately promoted；Master100仍依其gate。

Semantic IR v1只保留人工rollback；不得automatic fallback、retry、second/judge model或silent repair。Semantic Confirmation remains the entire fallback lifecycle forHuman Review writes, including exact immutable payload, local zero-call Confirm/Correct/Cancel, stale/scope/revision validation and atomic commit。

本次governance reconciliation後，runtime implementation可由**另一個明確授權的future task**開始。既有Phase 1–3B成果不在本治理任務重作；精確下一階段是 **Phase 3B.1 — application-derived unique exact literal resolution**。Phase 4仍未獲授權。

## 30. Migration / Rollback Strategy

先以SQLite backup與schema version gate建立rollback point。Schema v6只additive新增nullable `slot_id,registry_version,entity_id`於適用Current/History/Proposal identity；不得轉換prose、猜測backfill、把舊semantic_key當slot_id或改stable memory_id。啟動驗version，失敗rollback，rerun idempotent；dual-reader先上線，new writer/routing後續phase才可啟用。

Typed-engine/schema 歷史 rollback 仍依原規則處理。Proposal-metadata rollback必須保留新增nullable columns與已建立的新proposal payload，或在停用new writer前完成schema-aware export/restore；不得用舊executor解讀new semantic rows。Boundary rollback則是人工 configuration/deployment 選擇：在 turn 開始前整體選擇新 IR pipeline 或舊 13-key pipeline；不得因新 IR call/validation/compiler 失敗而對同一 turn自動切舊protocol、重試或發出第二次DeepSeek call。全程不改user IDs、stable memory IDs、history lineage與Current authority。

## 31. Paid-API Verification Budget

本規劃任務 paid calls=`0`。原始六階段與先前14-case boundary計畫保留為歷史而不自動授權未來呼叫。Architecture D與Semantic Confirmation的schema、routing、Confirm/Cancel/Correct、transaction、compiler、grounding、renderer、validation、firewall、UI guards、isolated exact-oracle runner與offline adversarial階段必須為0 paid calls；全部offline gates通過後，仍須由後續task明確授權capped Real40-v2。Master100只有在Real40-v2 acceptance後才可執行。不得為追求pass自動重試。

## 32. Remaining User Decisions

已解決：Architecture B typed engine（POLICY-05–09）；boundary/reply/one-call（POLICY-10–14）；Architecture D grounding（POLICY-15）；registry-constrained IR（POLICY-16）；Count/Set authority（POLICY-17）；risk-classified selective confirmation（POLICY-18）；immutable proposal identity（POLICY-19）；Canonical Slot Registry/entity/schema v6（POLICY-20）；Risk Engine（POLICY-21）；frozen benchmark/STOP（POLICY-22）。

Remaining user-policy decisions：`NONE`。

## 33. Risks

- DeepSeek仍可能選wrong-but-valid ID/type/intent；typed state只縮小錯誤面，不消除semantic風險。
- Ontology-managed `semantic_key`若被模型生成或當lineage identity會重引入free-text matching；必須由registry derive且stable `memory_id`仍為lineage authority。
- dual legacy/typed期間可能有疑似duplicate slot；安全結果是clarify/fail closed，不可auto-merge。
- 新 Semantic IR 仍可能因 intent/state/action/basis 選錯而失敗；per-intent schema減少serialization負擔，但不能消除model-semantic uncertainty。
- Exact grounding只能證明literal provenance，不能證明claim shape、target或`五 -> 5`等numeric interpretation；這些仍是model-semantic limitation。
- Count→Set cross-type history須由future same-ID atomic transition明確實作與測試；未完成前只能fail closed/clarify，不能建立parallel lineage。
- Human Confirm不證明objective truth；Risk Engine也不證明semantic truth，故production auto必須受frozen zero-unsafe benchmark及STOP rule約束。
- Schema v6 migration或legacy dispatch錯誤可能造成identity混淆；必須nullable additive fields、strict versioning、no guessed backfill。
- clarification若不具expiry/scope會污染後續request；若過度阻擋又會傷害unrelated flow。
- typed state size/range已由POLICY-06決定；風險轉為validator是否對每一路徑一致fail closed且不截斷。
- rollback若舊binary不懂typed rows可能資料不可見；需version gate與export/restore drill。
- 20 automated tests無法逐一容納76 contracts、SC/AD/OR matrices與42 scenarios；需parameterized subtests與traceability，不能以test count冒充coverage。
- Manual/live驗證具有機率性；不得將單次pass升格為deterministic guarantee。

## 34. Recommended Target

typed-engine/persistence保持 **Architecture B**。Model-facing boundary為 **Architecture D + application-owned Canonical Slot Registry + deterministic Risk Engine**：constrained extraction → grounding → registry/compiler → typed preconditions → auto atomic commit or Human Review Semantic Confirmation。D不取代B；selective routing取代universal confirmation。

理由：A無法關閉核准 set/count/record contracts的validator gaps；C一次將所有legacy與relation全面typed化，對1–2 user prototype的migration、API與維護風險過高；B保留已正確的stable-ID、SQLite、History、Pending、revision與transaction架構，只把高價值的 scalar/set/count/record transition typed化。Relation先由Set表示可避免雙重權威；legacy gradual migration避免模型/heuristic批次猜測。此選項以中等複雜度換取membership、count、field、empty-set、reassert與proposal policy的deterministic guarantees，同時不虛稱自然語言target selection已確定化。

## 35. Approval Status

`APPROVED_IMPLEMENTATION_PLAN`

本文件是已核准的typed-engine implementation history/plan；三份治理文件仍定義行為。Architecture D + Slot Registry + Risk Engine是model-facing target；Architecture B保持有效；additive schema v6與既有Phase 1–3B成果保持。Semantic IR v1只保留人工rollback；其legacy model-authored offsets不自動移植到ontology constrained IR，且不得automatic fallback。本次未執行runtime/tests/database/provider/UI/ZIP。六份文件已同步application-derived unique exact literal resolution、cardinality numeral／direct-classifier boundary與`POLICY-16`及`POLICY-18`–`POLICY-22`；`GOVERNANCE RECONCILIATION STATUS = COMPLETE`。治理衝突：無；remaining decisions：NONE。既有D3 `五位`結果為`PASS AS SEMANTICALLY ACCEPTABLE`且不需重跑；精確下一步是human manual D4，之後仍須D5。Phase 4仍未授權。


## 31. Post-Benchmark Human-Reviewed Product Plan

Automatic semantic memory implementation path已依`POLICY-22`終止：正式freeze `freeze-v1.2-6fb6d482f9b2142c53ca`在122/660即出現`HB-OFFICE-100 unsafe_auto_commit=true`並鎖住run。舊Phase 6–10的「Risk auto route → held-out PASS → production enablement」只保留為歷史紀錄，不再是目前產品待辦。

目前唯一product target是`HUMAN_REVIEWED_MEMORY_ASSISTANT`，且`POLICY-23`要求所有model-derived changed write都經Human Review。Remaining implementation order固定為：

1. **HR-P1 Governance/hard lock/status**：新增product status，顯示automatic stopped/human-reviewed retained；server端禁止archived held-out/preflight續跑；production auto-commit=false。
2. **HR-P2 Production ontology shadow**：以Normal Chat真實typed snapshot建立候選與preconditions；只preview，零proposal/零mutation；人工UI逐題驗證。
3. **HR-P3 Proposal-only cutover**：將validated changed ontology action轉成production Semantic Confirmation Proposal；Current/History/revision在Confirm前不變。
4. **HR-P4 Local resolution integration**：Confirm/Correct/Cancel重用既有Phase-3 executor；0 provider calls；schema v6 identity exact；stale/user/session/revision fail closed。
5. **HR-P5 Manual UI acceptance**：CREATE_SCALAR、SET_VALUE、SET_COUNT、ADD_ITEM、destructive REMOVE_ITEM、NOOP、TARGET_NOT_FOUND、UNKNOWN_SLOT至少各一個真人UI checkpoint。
6. **HR-P6 Final regression/release**：20/20 strict tests、py_compile、protected DB hash、restart、cross-session、user isolation、產品banner/README/archive狀態一致。

任何phase不得重新啟用`AUTO_COMMIT_ALLOWED` production route；若code path仍存在作歷史型別/benchmark fixture，production router必須hard-lock為Human Review或fail closed。
