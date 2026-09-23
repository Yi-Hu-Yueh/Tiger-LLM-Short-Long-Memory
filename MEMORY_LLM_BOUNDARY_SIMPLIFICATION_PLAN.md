# LLM → Application 邊界簡化計畫

- 文件狀態：`APPROVED_BOUNDARY_SIMPLIFICATION_PLAN`
- 文件性質：已核准的 model/application boundary 設計與候選遷移計畫；不是 runtime 實作授權，且不凌駕三份行為治理文件
- 核准方案：**D — Grounded Claim-Shape Semantic IR v2 + exact source-grounding validator + deterministic claim-shape compiler**；原 Architecture C Semantic IR v1 僅保留人工 rollback
- 審查範圍：DeepSeek 回傳 JSON、應用層驗證／編譯、既有 typed-memory 執行引擎之間的責任邊界
- 明確非目標：不以Python自然語言heuristic修復模型、不增加第二次LLM呼叫、不建立general-purpose ontology engine；schema方向只允許`POLICY-20` additive v6 nullable identity fields，不得猜legacy backfill或加入duplicate canonical payload blob

## 1. Executive Summary

目前系統把一個固定 13-key `decision` 物件交給 DeepSeek 填寫，再由應用層檢查 `kind`、`operation`、`evidence`、`state_type`、欄位空值規則、回覆規則與 proposal 規則。這個設計的安全核心是正確的：最終狀態轉移、stable memory ID、revision、歷史、proposal、ownership、transaction 與 fail-closed 都由應用程式控制。然而，模型同時被要求表達「使用者語意」與「應用程式內部控制協定」，形成大量可由程式推導、卻仍要求模型精確重複的欄位。

使用者已核准方案 D加Canonical Slot Registry / Risk-Classified Semantic Writes：DeepSeek輸出小型claim-shape IR並從application candidates選canonical slot/entity/target；application依序做structure、exact grounding、registry resolution、claim-shape compilation、Architecture B preconditions及deterministic Risk Engine。只有完整低風險條件才可`AUTO_COMMIT_ALLOWED`；其餘changed writes default `HUMAN_REVIEW_REQUIRED`並沿用Semantic Confirmation。這不是把語意判斷偷偷搬到Python；application不以NLP、fuzzy或normalization猜缺漏語意。

核心量化結果：

- 現況模型每次固定輸出 14 個 leaf fields（top-level `reply` 加 13 個 decision fields；若把 `decision` container 也算入 JSON key，則是 15 keys）。
- 模型目前要精確掌握 8 個 `kind`、15 個唯一 canonical operation tokens（18 個 state-qualified 合法組合）、11 個 evidence tokens，以及大量 null／empty／reply／proposal 規則。
- 建議 IR 改為每個 variant 通常 2–7 個主要欄位；`CLARIFY` 另帶一個重用的 nested candidate。模型不再輸出 canonical operation token、clarification ID、proposal policy 或 exact internal evidence token。
- Semantic IR v2 使用 claim-shape variants：`SCALAR_ASSERTION`、`CARDINALITY_ASSERTION`、`ENUMERATION_ASSERTION`、`MEMBERSHIP_ASSERTION`、`FIELD_ASSERTION`、`EXPLICIT_DELTA`、`FORGET`，以及 `READ|CLARIFY|FREEFORM|TARGET_NOT_FOUND|ABSTAIN` controls/intents。
- 既有typed-memory state machine與stable lineage保留。`POLICY-20`核准additive schema v6方向：在適用Current/History/Proposal加入nullable `slot_id,registry_version,entity_id`；legacy readable、no guessed backfill，且不得把舊`semantic_key`重解讀成canonical slot ID。

本計畫不是「讓應用程式自行理解中文」。模型仍負責真正的語意判斷，例如intent、claim shape、目標記憶、explicit operand semantic role與exact `claimed_literal` selection及genuine ambiguity。應用層負責strict structure、unique exact substring resolution、authoritative offset/slice derivation、claim-shape restricted compilation與既有typed-state preconditions。Offset counting不是ontology model責任。Exact grounding證明provenance，不證明model-selected literal的semantic correctness，也不證明例如`五 -> 5`的numeric interpretation；兩者仍是model-semantic limitation。

### Approved Policies

- `POLICY-10`：Architecture C Semantic IR v1是已核准歷史基礎；依`POLICY-16`現只保留人工rollback，未來target為Architecture D v2。
- `POLICY-11`：DeepSeek 不再擁有 exact internal kind/operation/evidence、Proposal policy、固定空欄位、clarification ID、revision/history behavior 或 deterministic acknowledgements；compiler 不得 semantic repair。
- `POLICY-12`：reduced basis 六值已核准；只有唯一安全 mapping 才可推導 existing internal evidence。
- `POLICY-13`：authoritative read/history/unknown、mutation/proposal/confirm/cancel/noop、TARGET_NOT_FOUND，以及可安全固定表達的 ABSTAIN/validation reply 由 application deterministic render；model prose 原則上限於 FREEFORM/CLARIFY。
- `POLICY-14`：one normal turn one DeepSeek call；舊13-key只保留人工rollback；schema方向由`POLICY-20` v6規範。
- `POLICY-15 — Exact Grounding of Explicit Literal Operands`：model選non-empty exact `claimed_literal`；application只在current turn恰一個exact occurrence時衍生authoritative span/slice；zero=`LITERAL_NOT_FOUND`、multiple=`LITERAL_AMBIGUOUS`；no first-match/normalization/fuzzy/NLP/retry；失敗在compiler前整回合fail closed。
- `POLICY-16 — Registry-Constrained Grounded Claim-Shape Semantic IR v2`：模型選supplied canonical slot/entity/target candidates及grounded operands；application derivation metadata/family/op；不得重建13-key protocol或製造identity。
- `POLICY-17 — Count and Enumeration Single Authority`：cardinality-only→Count；grounded enumeration/combined→Set only；same-ID Count→Set transition；Set count equal→NOOP、conflict→CLARIFY。
- `POLICY-18 — Risk-Classified Model-Derived Semantic Writes`：所有changed candidates先經application-owned deterministic Risk Engine；明確low-risk可atomic auto-commit，其他default Human Review；model confidence不授權。
- `POLICY-19 — Immutable Semantic Proposal Payload Identity`：Human Review proposal持久化normalized exact commit identity及registry-derived slot/entity metadata；Confirm/Cancel零provider call。
- `POLICY-20 — Canonical Slot Registry and Entity Identity`：immutable/versioned registry；memory/slot/entity identity分離；known-slot key/label由application衍生；schema v6方向。
- `POLICY-21 — Deterministic Risk Engine and Selective Confirmation`：全部low-risk條件、always-review classes、conservative initial candidates與default review。
- `POLICY-22 — Frozen Ontology/Risk Benchmark and Project STOP Rule`：DeepSeek v4 Pro first、frozen ≥600-turn held-out gate、zero unsafe、thresholds與mandatory STOP。

### 1.1 Architecture D authoritative boundary

Architecture D 取代 Architecture C Semantic IR v1 作為未來 production write-boundary direction：

```text
canonical current user turn
    -> one DeepSeek call
    -> constrained Semantic IR v2 slot/entity/claim extraction
    -> strict structural validator
    -> exact source-grounding validator
    -> Canonical Slot Registry resolution
    -> deterministic claim-shape compiler / family / operation derivation
    -> existing Architecture B typed-precondition resolver
    -> deterministic Risk Engine
       -> AUTO_COMMIT_ALLOWED -> atomic History / Current / revision commit
       -> HUMAN_REVIEW_REQUIRED -> immutable semantic-confirmation proposal
          -> explicit local Confirm / structured Correct / Cancel
          -> transaction-time revalidation -> atomic commit
```

Semantic IR v1是人工rollback path；不得per-turn automatic fallback、retry、second/judge model或semantic repair。下文歷史分析凡與本節及`POLICY-15`–`POLICY-22`不同，均由registry-constrained Architecture D + deterministic risk routing取代。

### 1.2 Semantic IR v2 responsibility split

- Model：semantic intent、provided registry中的canonical `slot_id`或`UNKNOWN_SLOT`、provided existing entity/target selection、claim shape、explicit operand semantic role與exact `claimed_literal`、genuine ambiguity及semantic numeric interpretation；不負責authoritative character offsets。
- Structural validator：protocol version、variant、required/forbidden fields、types、counts、range shape；不讀取語意。
- Literal resolver / grounding validator：以exact canonical model-visible current-turn text（既有outer trim後、Unicode normalization前）對每個non-empty `claimed_literal`計算全部Python exact occurrences。恰一個→`RESOLVED_EXACT`並衍生authoritative zero-based half-open Python/code-point span與slice；零個→`LITERAL_NOT_FOUND`；多個→`LITERAL_AMBIGUOUS`。任一required literal失敗使整個executable changed write fail closed；不得first-match、partial grounding、NFC/NFD/NFKC/case/punctuation/whitespace normalization、tokenization、regex semantic inference、fuzzy/synonym/translation/alias/NLP/keyword修補。
- Slot Registry/compiler：validate registry version/slot；derive family/value type/key/label/allowed op；`CARDINALITY_ASSERTION -> Count`、`ENUMERATION_ASSERTION -> Set`、`MEMBERSHIP_ASSERTION -> Set membership`；不得製造identity。
- Architecture B typed-precondition resolver：ownership、target existence、typed limits、canonical equality、Current/History/revision與Count/Set representation-transition preconditions。
- Risk Engine：pure deterministic input/output；default`HUMAN_REVIEW_REQUIRED`。只有all low-risk conditions PASS且slot/operation明示enable才可`AUTO_COMMIT_ALLOWED`；model confidence無效。
- Semantic-confirmation gate：只處理`HUMAN_REVIEW_REQUIRED`；NOOP/non-write bypass；application負責proposal identity/rendering/binding，user負責確認exact proposed interpretation。

Ontology constrained identity-bearing operands SHOULD只帶model-selected `claimed_literal`；application-derived unique exact `source_start/source_end`與slice是authoritative provenance。若遷移期保留model offsets，只可標為non-authoritative diagnostics且不得影響grounding acceptance。若numeric或其他shape另帶model-interpreted canonical value，source literal與canonical value必須分離，grounding不得被誤報為literal semantic correctness或canonical conversion正確性證明。

`CARDINALITY_ASSERTION`的model-selected exact literal可為numeral token，或為該numeral與直接相連classifier構成的exact contiguous quantity phrase（例如`五`／`五位`）。兩者是否保留由separate model-semantic `canonical_value`表示的同一cardinality，由model及human/preregistered oracle判斷；application只作unique exact resolution並原樣保留literal，不解析或剝除classifier、不normalize、不repair，也不允許任意周邊noun phrase。此規則不適用於R05等Scalar boundary；`色。`仍是material value缺失的semantic error candidate。

`POLICY-17` 的單一權威規則：cardinality-only只可一個Count；complete grounded enumeration只可一個Set且count=`len(unique items)`；combined assertion只可Set且count mismatch fail closed。Existing Count收到complete grounded enumeration時，在preconditions成立後先形成same-ID semantic proposal；Confirm後才atomic Count→History predecessor→Set Current、revision +1 once。Existing Set收到相等count為NOOP且不提案，不相等count為CLARIFY且零mutation。

責任邊界：MODEL owns semantic intent、constrained slot/entity/target selection、claim shape、operand semantic role與exact `claimed_literal`、ambiguity、model-semantic canonical numeric value與允許的prose。APPLICATION owns exact occurrence count、unique resolution status、authoritative offsets/slice、registry、canonical metadata、structural/grounding validation、family/operation/preconditions、Risk Engine、routing、proposal、History/revision/transactions/replies。USER owns confirmation on Human Review path。Grounding、risk與confirmation均不證明objective semantic truth。

Default diagnostics不得包含raw user text、raw operand、source slice、API secret或full IR；只可記錄protocol version、claim shape、operand count、occurrence count、span lengths、resolution status、PASS/FAIL與deterministic reason code。

### 1.3 Canonical Slot Registry and entity boundary

`SlotDefinition`的最小schema為`slot_id,entity_scope,typed_family,value_type,allowed_claim_shapes,allowed_operations,grounding_required,default_display_label,risk_class,auto_commit_allowed`。初始registry只含：`user.office.location`,`vehicle.color`,`pet.name`,`group.members`,`group.member_count`,`ownership.owner_profile.name`,`ownership.owner_profile.address`,`user.favorite_drink`,`user.birth_month`,`desk.floor`,`device.phone.model`,`person.residence.location`。不建立general-purpose ontology engine。

`memory_id`是lineage identity；`slot_id`是semantic property schema；`entity_id`是application-owned stable real-world instance identity。Ordinal mention只可協助模型從server-provided candidates選existing entity，不得成為ID。Known ontology slot的`semantic_key`由application衍生且等於canonical `slot_id`；`display_label`來自registry/application。`UNKNOWN_SLOT`不得auto-commit或自動擴registry。

Registry version `1` exact labels：`user.office.location=辦公室位置`；`vehicle.color=車輛顏色`；`pet.name=寵物名字`；`group.members=群組成員`；`group.member_count=群組人數`；`ownership.owner_profile.name=所有權人姓名`；`ownership.owner_profile.address=所有權人地址`；`user.favorite_drink=最愛飲料`；`user.birth_month=出生月份`；`desk.floor=書桌所在樓層`；`device.phone.model=手機型號`；`person.residence.location=居住地點`。Application只做exact lookup；不得runtime translation、從slot/user prose演算法產生、fuzzy/alias或model generation。Label change要求registry-version/governance change。Entity-aware presentation可另外組合entity name，不能改generic registry label。

### 1.4 Deterministic Risk Engine

Input固定為validated `slot_id`、entity scope、operation、claim shape、grounding result、typed-precondition result、registry version及slot policy；output固定為`AUTO_COMMIT_ALLOWED`,`HUMAN_REVIEW_REQUIRED`或既有non-write/fail-closed。Auto要求全部成立：slot存在且slot/operation明示auto、scope/target unambiguous、grounding PASS、non-destructive、無ontology extension、無family/Count↔Set transition、typed preconditions PASS、無conflict/clarification/unknown target、可atomic commit且slot-specific validation PASS。任何缺漏default Human Review。

Always-review：`UNKNOWN_SLOT`、uncertain new entity、ambiguous target/entity、destructive op、`DELETE_MEMORY`,`REMOVE_ITEM`,`DELETE_FIELD`、Count↔Set或state-family transition、semantic correction、ontology extension、conflict、unsupported op、record-schema uncertainty。初始benchmark-only auto candidates僅`user.office.location,user.favorite_drink,user.birth_month`；`pet.name,device.phone.model,desk.floor`只可held-out PASS後另案提升；`vehicle.color`與`group.member_count`初始review-required。沒有slot因registry membership自動取得production auto權限。

### 1.5 Frozen benchmark and STOP rule

Production enablement前凍結model/parameters/prompt/registry/version/risk rules/held-out data/procedure，DeepSeek v4 Pro先測。至少600個preregistered auto-eligible turns；unsafe=0；forbidden-risk auto=0；slot-selection、operand/value、protocol failure各≤1%；Human Review≤35%；safe automatic completion≥65%。對`CARDINALITY_ASSERTION`，preregistered semantic oracle若判定numeral token與exact numeral+direct-classifier phrase保留同一cardinality，不得只因該granularity差異計為operand/value error。Wrong number/slot/entity/shape/canonical value、unrelated/over-broad/missing-meaning literal或wrong authoritative result仍是error。`UNSAFE AUTO-COMMIT`定義與threshold完全不變，涵蓋wrong slot/entity/target/operand/value/span/op/semantics-changing claim shape/typed result/authoritative mutation，包括R05 wrong value boundary。

> After the frozen ontology/risk benchmark, if ANY unsafe auto-commit occurs, any forbidden-risk write auto-commits, or at least 65% safe automatic completion cannot be achieved without weakening safety rules, the project MUST STOP pursuing automatic semantic memory and retain only Human-Reviewed Memory mode. The held-out dataset and thresholds MUST NOT be changed, thresholds relaxed, or ad-hoc prompt exceptions added after results are observed. A materially new architecture or model requires a separately approved evaluation.

## 2. Why Current Protocol Is Brittle

現行邊界脆弱，不是因為 JSON 本身，而是因為同一個模型輸出同時混合四類責任：

1. **語意分類**：這是模型真正擅長且無法完全以規則取代的部分，例如 READ 或 CHANGE、scalar 或 set、目標 memory ID、是否需要澄清。
2. **內部 opcode 編碼**：例如 `SET_VALUE`、`REPLACE_SET`、`SET_FIELD`。這些可由 `state_type + semantic action + arguments` 決定性映射。
3. **政策選擇**：例如 destructive change 必須是 `PROPOSE` 而不能直接 `MUTATE`。這應由應用程式依 canonical operation 推導。
4. **協定 bookkeeping**：例如 `clarification_id`、未使用欄位必須是空陣列／空字串／null、某些 kind 是否必須有 reply。這些應由應用層建立或由 per-variant schema 消除。

固定 13-key 形式讓每個請求都攜帶大量不相關欄位。即使模型已正確理解使用者意圖，只要多填一個欄位、少清空一個欄位、選錯同義 opcode、回覆欄位不符合 kind 規則，就會被 fail-closed 拒絕。Fail-closed 本身必須保留；應被移除的是不必要的失敗表面。

現行 prompt 還要求模型同時維持兩套相互依賴的枚舉：`operation` 與 `evidence`。例如模型不只要知道「這是完整集合替換」，還要輸出正確 state-specific operation 與相容 evidence。任何一邊錯誤都失敗；而應用層其實已有足夠結構資訊映射 exact internal token。

## 3. Real Failure Evidence

以下分類來自現有實作、測試與治理文件所呈現的失敗面；編號用於後續風險矩陣。

| ID | 失敗類型 | 現況成因 | 方案 C 預期效果 |
|---|---|---|---|
| F-01 | 明確 scalar 敘述仍回 `CLARIFY` | 模型語意判斷失誤 | **保留**；這是真正模型語意限制，只能以更清楚 variant/schema 與 live conformance 降低，不能由 Python 改寫 |
| F-02 | unused fields 非空／null 型態錯 | 固定 13-key 物件迫使模型維護大量空值 | **消除**；discriminated union 不允許也不要求無關欄位 |
| F-03 | READ 夾帶 mutation 欄位或非法 state 欄位 | kind 與全域欄位矩陣重疊 | **大幅降低／可 schema 消除** |
| F-04 | operation token 拼錯或 state-operation 不相容 | 模型直接輸出內部 opcode | **消除**；compiler 決定 canonical operation |
| F-05 | `NOOP` reply 空白而被拒 | reply policy 由模型記憶 | **消除**；應用層產生 deterministic NOOP acknowledgement |
| F-06 | count vs set 混淆，或集合內容由模型補造 | 真正語意分類錯誤；operation/evidence 重複表達又擴大錯誤面 | **保留但縮小**；模型仍須判斷 state 與 `basis`，compiler 不可猜；嚴格 basis gate 繼續 fail closed |
| F-07 | destructive operation 以 `MUTATE` 直接提交 | 模型同時選語意與 policy | **消除**；proposal policy 由 compiler 依 operation 決定 |
| F-08 | clarification ID 缺漏、錯 user/session 或 stale | 模型被要求回傳應用狀態識別 | **消除**；應用程式建立並綁定 active clarification context |
| F-09 | READ reply 與資料庫現值矛盾 | 自由文字被誤當權威 | **既有機制已控制**；方案 C 明確讓 READ 只選 IDs，值仍由 SQLite render |
| F-10 | create metadata 與 mutation target 混用 | global fixed fields 缺乏 variant locality | **大幅降低**；`slot` 僅存在於 create variant |

不能宣稱方案 C 消除 F-01 或 F-06。它們含有模型語意決策；本計畫只能讓輸出協定更正交、更容易約束與測試，並保留 fail-closed。

## 4. Current Model-Facing Protocol

現行 provider envelope 以 `response_format: {"type": "json_object"}` 要求 JSON object。成功內容含：

- top-level `reply`
- top-level `decision`
- `decision` 內固定 13 keys：
  - `arguments`
  - `clarification`
  - `clarification_id`
  - `current_memory_ids`
  - `display_label`
  - `evidence`
  - `history_ids`
  - `kind`
  - `memory_id`
  - `operation`
  - `semantic_key`
  - `state_type`
  - `unknown`

`kind` 有 8 種：`READ`、`MUTATE`、`PROPOSE`、`CLARIFY`、`NOOP`、`FREEFORM`、`ABSTAIN`、`TARGET_NOT_FOUND`。

唯一 canonical operation tokens 共 15 種；因同一 token 在不同 state type 可重用，state-qualified 合法組合共 18 種：

- Scalar：`CREATE_SCALAR`、`SET_VALUE`、`REASSERT_NOOP`、`DELETE_MEMORY`
- Set：`CREATE_SET`、`ADD_ITEM`、`REMOVE_ITEM`、`REPLACE_SET`、`DELETE_MEMORY`
- Count：`CREATE_COUNT`、`SET_COUNT`、`INCREMENT`、`DECREMENT`、`DELETE_MEMORY`
- Record：`CREATE_RECORD`、`SET_FIELD`、`DELETE_FIELD`、`DELETE_MEMORY`

Evidence tokens 共 11 種：`EXPLICIT_ASSERTION`、`EXPLICIT_COMPLETE_STATE`、`EXPLICIT_TARGET_ITEM`、`EXPLICIT_FIELD`、`EXPLICIT_FIELD_VALUE`、`EXPLICIT_DELTA`、`EXPLICIT_FORGET`、`CONTINUATION`、`INSUFFICIENT`、`READ_SELECTION`、`NONE`。

這套協定已具備強大驗證，但模型所見格式幾乎等同應用程式內部 IR。邊界簡化的目標不是刪除內部嚴格性，而是把這套內部 IR 隱藏在 deterministic compiler 後方。

## 5. Current Complexity Inventory

現況的模型負擔可量化如下：

| 維度 | 現況 |
|---|---:|
| 每次必須存在的 leaf fields | 14 |
| 若計入 `decision` container 的 JSON keys | 15 |
| `kind` variants | 8 |
| 唯一 canonical operation tokens | 15 |
| state-qualified operation 組合 | 18 |
| exact evidence tokens | 11 |
| decision 欄位的 canonical default／empty 值 | 10 類以上 |
| destructive policy 分流 | 模型須自行選 `PROPOSE` vs `MUTATE` |
| reply policy | 8 kind 中有 5 類依賴 non-empty model reply，3 類可由應用層 render／替代 |
| clarification bookkeeping | 模型須攜帶／回傳 clarification 狀態欄位 |

複雜度不是單純 14 個欄位，而是欄位間的笛卡兒相容性：`kind × state_type × operation × evidence × arguments × reply × proposal policy`。現有 validator 正確拒絕非法組合，但 prompt 對模型而言必須描述幾乎相同的矩陣，因此容易發生「語意正確、編碼錯誤」。

## 6. Field-by-Field Responsibility Audit

分類定義：

- **A**：必須保留為模型直接產生的現行欄位。
- **B**：應由應用程式決定性推導。
- **C**：應消除或改由 discriminated variant 結構表達。
- **D**：仍屬模型語意輸入，但只應出現在相關 variant。
- **E**：在實作前仍需治理／產品決策。

每個現行模型欄位只指定一個分類：

| 現行欄位 | 語意用途 | 模型是否真的需要決定 | 可否由應用程式推導／驗證 | 主要失敗模式 | 建議 | 分類 |
|---|---|---|---|---|---|---|
| `reply` | 自由文字回覆 | 現行 contract 對 FREEFORM、CLARIFY、ABSTAIN、TARGET_NOT_FOUND 要求；核准未來邊界原則上只由 FREEFORM/CLARIFY 產生 | READ、status、mutation/proposal/noop 可由 application render | **F-05** 空 reply；另有與 DB 值矛盾、混入未提交狀態風險 | 僅放在 FREEFORM/CLARIFY；治理明確例外另論 | D |
| `kind` | 控制大分流 | 模型必須判斷語意 intent，但不必知道現有 8-kind 內部控制層 | compiler 可把較小 intent union 映射成內部 kind | **F-01、F-03**；另有 PROPOSE/MUTATE policy 錯 | 移除現行 key，改用 per-variant `intent` discriminator | C |
| `state_type` | scalar/set/count/record | 模型需要做語意分類 | 應用可驗證但不能從任意中文可靠推導 | **F-06** count/set 混淆 | 僅在 change/candidate variant 出現 | D |
| `operation` | 精確內部 opcode | 不需要；模型只需表達較小的 semantic action | 可由 `state_type + action + args` 決定性映射 | **F-04** invented token；另有 state 不相容、同義操作選錯 | 不再由模型輸出 | B |
| `evidence` | evidence gate 的精確內部 token | 模型仍需提供不可推導的語意 basis；不需輸出 11-token 內部枚舉 | compiler 可由精簡 `basis + intent/action` 映射 exact token | **F-06** 與 state/action 矛盾；另有 complete-state、delta、target item 選錯 | 移除現行 token；保留較小 variant-local `basis` | B |
| `memory_id` | 指定既有 lineage | 更新／刪除／read target 需要模型選；create ID 必須由應用產生 | ownership/existence/revision 可驗證；語意 relevance 不可完全推導 | 未直接造成 F-01–F-06；潛在選錯 target、跨 user ID | 改名 `target_id`，只在需要 target 的 variant | D |
| `semantic_key` | ontology compatibility metadata | 歷史v1曾由model提供；Registry-v1 target禁止 | application exact derives `semantic_key=slot_id` | model wording與slot identity風險 | Registry-owned exact value | D + POLICY-20 |
| `display_label` | UI 顯示名稱 | 歷史v1曾可能由model生成；Registry-v1 target禁止 | application exact lookup versioned canonical label | dynamic translation／亂填風險 | Registry-owned exact value | D + POLICY-20 |
| `arguments` | mutation payload | 模型必須抽取使用者明示的值／item／field／delta | 可做型別、完整性、長度與 operation compatibility 驗證 | **F-02、F-03、F-06**；缺值、補造集合、錯型別 | 改為 variant-local `args` | D |
| `current_memory_ids` | READ 選定 current lineages | 模型須做 relevance selection | 應用做 ownership／existence 驗證；不可用 fuzzy rule 代選 | **F-02、F-03**；另有選錯或越權 ID | 僅 READ variant 出現 | D |
| `history_ids` | READ 選定歷史 records | 模型須做 relevance selection | 應用做 ownership／lineage 驗證 | **F-02、F-03**；另有把 history 當 current 風險 | 僅 READ variant 出現 | D |
| `unknown` | 明示個人記憶查無資料 | 需要模型判斷問題是在問個人記憶且沒有相關 ID | 應用能驗證 ID 空集合與 unknown 相容，不能決定任意問題語意 | **F-02、F-03**；空 ID 卻未 unknown 或錯誤 unknown | 僅 READ variant 出現 | D |
| `clarification` | 缺少資訊與候選動作的包裝 | 模型需指出缺什麼與問題；不需手工維護現行 wrapper 形狀 | variant schema 可直接表達 candidate/missing/question | **F-01、F-02**；wrapper 與頂層欄位重複 | 移除現行 wrapper，改 `clarify` variant | C |
| `clarification_id` | 綁定 pending clarification | 模型不需要也不應決定 | 應用可依 user/session/active revision 建立與綁定 | **F-02** fixed-key burden；另有 stale、跨 session、偽造 ID 風險 | 完全由應用層建立與驗證 | B |

結論：現行欄位沒有任何一個需要以「固定全域欄位、每次都輸出」的形式保留。真正的模型語意欄位保留在相關 variant；內部 token 與 bookkeeping 由 compiler／runtime 產生。

## 7. Decision-Kind Audit

| 現行 kind | 真正語意 | 現況額外負擔 | 建議 IR | 內部結果 |
|---|---|---|---|---|
| `READ` | 選 current/history IDs 或明示 unknown | 必須清空 mutation 欄位、符合 reply/render 規則 | `intent: read` | compiler 產生 `READ` + `READ_SELECTION`；應用從 DB render |
| `MUTATE` | 現行非破壞性變更kind | 模型須知道現行協定是否直接提交 | `intent: change` | compiler產生changed candidate；`POLICY-18` proposal gate建立`SEMANTIC_CONFIRMATION` proposal，不直接commit |
| `PROPOSE` | 現行破壞性變更kind | 模型同時做語意與 policy 判斷 | 同一 `intent: change` | compiler產生changed candidate；同一proposal gate建立proposal並另衍生`destructive=true` |
| `CLARIFY` | 資訊不足，提出一個問題 | wrapper、ID、candidate 與 reply 多處重複 | `intent: clarify` | compiler 建立內部 clarification，runtime 綁定 ID |
| `NOOP` | 重申相同狀態或無變更 | 模型須輸出非空 reply 並選 NOOP kind | `intent: change` + `action: reassert`，或明確 `noop` variant | compiler 產生 `NOOP`，應用回固定 acknowledgement |
| `FREEFORM` | 非個人記憶的一般回覆 | 必須清空所有 decision 欄位 | `intent: freeform` + `reply` | 直接回覆，不進 memory mutation |
| `ABSTAIN` | 無法安全回答／拒絕 | 與 FREEFORM 結構近似但控制語意不同 | `intent: abstain`，通常不含 model reply | 內部 `ABSTAIN` + application safe response |
| `TARGET_NOT_FOUND` | 指定目標不存在或不可定位 | 與 abstain 結構近似 | `intent: target_not_found`，不含 model reply | 內部 `TARGET_NOT_FOUND` + application deterministic response |

`MUTATE`與`PROPOSE`不應是模型層兩個獨立意圖；它們是同一change intent。Application先決定typed changed/NOOP，再以Risk Engine選auto commit或Human Review proposal；destructive永遠review且是proposal的獨立effect flag。

## 8. Operation Vocabulary Audit

模型不需要知道 15 個 internal opcode。建議只輸出 9 個接近使用者語意的 action：

`create`、`set`、`add`、`remove`、`increment`、`decrement`、`delete_field`、`delete_memory`、`reassert`。

Compiler 使用下表產生 exact operation；沒有列出的組合一律拒絕，不能猜測：

| `state_type` | semantic `action` | 必要 args | canonical operation |
|---|---|---|---|
| scalar | create | value | `CREATE_SCALAR` |
| scalar | set | value | `SET_VALUE` |
| scalar | reassert | value | `REASSERT_NOOP` |
| scalar | delete_memory | — | `DELETE_MEMORY` |
| set | create | items | `CREATE_SET` |
| set | add | item | `ADD_ITEM` |
| set | remove | item | `REMOVE_ITEM` |
| set | set | items | `REPLACE_SET` |
| set | delete_memory | — | `DELETE_MEMORY` |
| count | create | value | `CREATE_COUNT` |
| count | set | value | `SET_COUNT` |
| count | increment | delta | `INCREMENT` |
| count | decrement | delta | `DECREMENT` |
| count | delete_memory | — | `DELETE_MEMORY` |
| record | create | fields | `CREATE_RECORD` |
| record | set | field, value | `SET_FIELD` |
| record | delete_field | field | `DELETE_FIELD` |
| record | delete_memory | — | `DELETE_MEMORY` |

這個 mapping 是語法與型別編譯，不是 semantic repair。若模型給 `state_type: count, action: add`，compiler 必須拒絕；不得偷改成 `increment`。若模型給 record `set` 卻沒有 field，compiler 必須拒絕或要求模型已輸出的 `clarify` variant；不得從中文自行猜 field。

## 9. Evidence Vocabulary Audit

Exact evidence token 應由 application compiler 產生，但 evidence 背後的「使用者到底明示了什麼」仍有模型語意成分。完全刪除 evidence 語意會造成風險：例如模型把「今天又發生一次」錯誤建成一個完整 set 並補造 items；若 compiler 僅因 `CREATE_SET + items` 就自動給 `EXPLICIT_COMPLETE_STATE`，會削弱目前 evidence gate。

因此核准保留一個較小、面向來源語意的 `basis`，只在 change／clarify candidate 中出現：

- `ASSERTION`
- `COMPLETE_ENUMERATION`
- `EXPLICIT_DELTA`
- `FORGET`
- `CONTINUATION`
- `INSUFFICIENT`

Compiler 再結合 intent/action/args 映射成現有 11-token evidence：

- READ → `READ_SELECTION`
- 非記憶控制類 → `NONE`
- clarify 缺資訊 + `INSUFFICIENT` → internal `INSUFFICIENT`
- active clarification follow-up + `CONTINUATION` → internal `CONTINUATION`
- `COMPLETE_ENUMERATION` + set create/replace + explicit items → `EXPLICIT_COMPLETE_STATE`
- `ASSERTION` + 已驗證 action/arguments → 視唯一 mapping 推導 `EXPLICIT_ASSERTION`、`EXPLICIT_TARGET_ITEM`、`EXPLICIT_FIELD` 或 `EXPLICIT_FIELD_VALUE`
- `EXPLICIT_DELTA` + admitted count delta → internal `EXPLICIT_DELTA`
- `FORGET` + destructive target/action → internal `EXPLICIT_FORGET`

如此模型不再同時記憶 `EXPLICIT_FIELD_VALUE` 這類 internal spelling，也不能因 application 自動把任何 payload 升格成強 evidence 而繞過安全政策。`basis` 仍是 model-semantic input，應用只能驗證其與 action/args 是否相容，不能保證其語意選擇永遠正確。

## 10. Reply Responsibility Audit

建議責任如下：

| 情境 | 回覆權威來源 | 理由 |
|---|---|---|
| READ current/history | SQLite + deterministic renderer | 防止 raw model wording 與 committed state 矛盾 |
| READ unknown | application 固定訊息 | 沒有可 render 值，且不應猜測 |
| mutation success | application 固定／模板化 acknowledgement | 寫入結果已由 runtime 知道 |
| proposal created | application 由 proposal payload render | Pending Proposal 才是權威，不應以自由文字取代 |
| NOOP/reassert | application 固定 acknowledgement | 消除 F-05 |
| CLARIFY | model `question`，但 application 包裝與綁定 context | 問題措辭需要語言能力；狀態不交給模型 |
| FREEFORM | model `reply` | 一般對話本來就是模型責任 |
| ABSTAIN/TARGET_NOT_FOUND | application deterministic safe response；只有治理明確要求自然語言說明時才可另案允許 model prose | 不得夾帶未提交 memory state |

這會把 `reply` 從全域必填概念縮成少數 prose variants 的欄位。任何 DB-based answer 仍由既有 deterministic rendering 產生。

## 11. Read Path Analysis

建議 READ IR：

```json
{
  "intent": "read",
  "current_ids": ["..."],
  "history_ids": ["..."],
  "unknown": false
}
```

模型只做三項真正需要語意能力的工作：判斷這是 personal-memory read、選 relevant stable IDs、判斷查無資料。應用繼續負責：

- ID ownership 與 user isolation
- current/history 類型與 lineage 驗證
- unknown 與 ID 集合的互斥規則
- current value 與 historical value 的 DB render
- 拒絕 raw model reply 覆蓋 committed state

READ variant 不應接受 `state_type`、`action`、`args`、`slot`、`basis`、`target_id` 或 proposal 欄位。若 provider 支援真正的 discriminated schema，這些欄位可在生成時排除；否則由本地 strict validator fail closed。

## 12. Write Path Analysis

Registry-constrained CHANGE IR概念（exact v2 union仍依Architecture D phase）：

```json
{
  "intent": "change",
  "state_type": "scalar",
  "target_id": "...或 create 時省略",
  "action": "set",
  "args": {"value": "..."},
  "slot_id": "user.office.location",
  "basis": "ASSERTION"
}
```

Known-slot create只允許model選application-provided canonical `slot_id`；`semantic_key/display_label`不在model output。`target_id`只允許existing-lineage action。欄位是否存在由variant schema決定。

Compiler 依下列順序處理，任何一步失敗即不產生 action：

1. 驗證 variant 與 exact allowed keys。
2. 驗證 primitive types、長度、enum。
3. 驗證 action/state 組合與 args shape。
4. 驗證target ID ownership/existence/revision或Registry-v1 `slot_id`/entity scope。
5. 從registry exact derivefamily、operation constraints、`semantic_key=slot_id`與canonical label。
6. 由 basis/context 產生 canonical evidence。
7. 由typed precondition決定changed或NOOP，再由Risk Engine選auto或Human Review；NOOP直接回no-change。
8. 建立internal transition或canonical review proposal；model不得授權commit。
9. 只有後續local Confirm通過scope/revision/Current/preconditions/payload identity重驗後，才交給既有atomic commit engine。

Compiler 絕不搜尋文字相似記憶、解析中文主詞、比較 value overlap，亦不重寫模型選擇的 target。

## 13. Count vs Set Analysis

Count 與 set 的差異不能靠 compiler 從 payload 形狀自動修好，因為兩者是語意狀態：

- 「我有三隻貓」可能是 count；除非逐一命名且表示完整成員集合，不能自動建 set。
- 「阿虎、阿花是我所有的貓」可構成 complete set，但仍依賴模型辨識完整性。
- 「今天又領養一隻」可形成 count delta；不能憑事件文字補造一個匿名 set item。

方案 C 的改善是：模型只需選 `state_type`、semantic action、args 與 basis，不再額外選 state-specific operation 及 evidence token。安全門仍保留：

- `CREATE_SET`／`REPLACE_SET` 必須有 `basis: COMPLETE_ENUMERATION` 且 items 完整有效。
- `ADD_ITEM`／`REMOVE_ITEM` 必須有 `basis: ASSERTION` 且 item 明確；application 由 action/args 唯一推導 target-item evidence。
- `INCREMENT`／`DECREMENT` 必須有 `basis: EXPLICIT_DELTA` 且 delta/target 明確，並繼續禁止匿名 membership event arithmetic。
- 如果只有「發生一件事」但沒有可安全定型的 state/target，模型應輸出 `clarify`；應用不可自行選 count 或 set。

因此 F-06 仍是 model-semantic limitation，但錯誤不再被 application compiler 靜默合理化。

## 14. Clarification Analysis

建議 CLARIFY IR 以 candidate 物件重用 change schema：

```json
{
  "intent": "clarify",
  "candidate": {
    "state_type": "record",
    "target_id": "...",
    "action": "set",
    "args": {},
    "basis": "INSUFFICIENT"
  },
  "missing": ["value"],
  "question": "要把這個欄位改成什麼值？"
}
```

應用層在接受後建立 opaque `clarification_id`，綁定 user、session、candidate、base revision、expiry/active state。後續訊息若模型表示 `basis: CONTINUATION`，compiler 只能在存在同 user/session active clarification 且 candidate 相容時補上 application-held context。模型不需看見或回傳 ID。

這個補 context 動作不是 semantic repair，因為 application 只恢復自己已保存的明確狀態；它不能把無關訊息強制解釋為 continuation，也不能替模型補出尚未明示的 value/item/field。

若 active clarification 已 stale、revision 不符、跨 session 或 candidate 不相容，必須 fail closed；不得重新詢問 LLM 來重建舊意圖。

## 15. Destructive Policy Derivation

Semantic confirmation與destructive effect policy都應完全移出模型。模型只表達change；application依typed precondition與canonical operation決定：

- 任何changed model-derived result → `purpose=SEMANTIC_CONFIRMATION` immutable Proposal
- destructive operation → 同一proposal另標`destructive=true`
- non-destructive changed operation → 同一proposal標`destructive=false`
- 重申同值／無狀態變更 → internal `NOOP`，不建立proposal

Runtime建立具體、validated、user/session/base-revision-scoped proposal，包含exact target/create semantics、typed operation、canonical operand/result、purpose、destructive flag與immutable payload identity。一個fully rendered destructive proposal的一次Confirm可同時確認semantic interpretation及授權effect，不要求two-confirm。Confirm/Cancel是0 DeepSeek calls的local state transition。

`POLICY-19`固定normalized persisted identity。所有new semantic rows保存`proposal_id,user_id,session_id,base_revision,purpose,destructive,payload_version=1,state_type,operation,arguments_json`與適用lineage欄位。CREATE由application在proposal creation配置final stable `memory_id`，保存exact `semantic_key/display_label`，且`target_memory_id=NULL`；此時不寫Current，Cancel後ID不回收。Existing-target mutation以`target_memory_id`為authoritative target，key/label可NULL且不得形成第二identity。Proposal renderer只從此persisted payload產生；Confirm只從同一payload加transaction-time authoritative state執行，禁止再生ID/key/label/arguments、重讀prose或semantic repair。`display_text/content`不是canonical identity；不新增canonical `payload_json`或required hash。Correct建立new proposal_id與new payload，不in-place改舊payload。

模型不得輸出`confirm: true`、不得建立proposal ID、不得自行宣布已提交、不得把pending value當current。Human Review result由proposal payload render；auto result只由committed deterministic transition render。Model prose不得成為authority。

Non-write routing：`NOOP`、`READ`、`TARGET_NOT_FOUND`、`ABSTAIN`、`FREEFORM`不建立memory-write proposal；`CLARIFY`在complete candidate形成前只走clarification lifecycle。Structured Correct若可直接編輯typed operand，可本地零call但必須建立新immutable proposal identity；自然語言Correct是新semantic turn且只允許該turn既有一次provider call。

## 16. Provider Structured-Output Capability Assessment

從現有 `DeepSeekClient.complete` 可確認的 repository evidence 僅有：

- endpoint 為既有 DeepSeek chat completions endpoint；
- model 為 `deepseek-v4-pro`；
- `thinking` disabled；
- `response_format` 使用 `{"type": "json_object"}`；
- 沒有在現有程式中使用 `json_schema`、tools、function calling 或 `tool_choice`。

因此，本審查只能確定目前整合具有 **JSON object mode**。Repository 內沒有證據足以聲稱該 endpoint/model 組合支援：

- provider-enforced strict JSON Schema；
- discriminated union schema；
- function/tool calling；
- strict additionalProperties rejection。

以上能力一律標記為 **EXTERNAL VERIFICATION REQUIRED**。在沒有官方文件／實際低成本驗證前，不應把它們列為方案 C 的必要前提。

方案 C 可在現有 JSON mode 上先落地：provider 只保證 JSON object，本地 validator 保證 strict union。若未來外部證據確認 provider 支援 strict schema，可再把同一 schema 上推 provider，降低 malformed output，但本地 validation 仍不可移除。

## 17. Candidate Design A — Current Protocol

**定義**：保留現有固定 contract，只調整 prompt 範例／文字。

優點：

- 零 migration，零 compiler 新層。
- 現有 20 tests 與 runtime 幾乎不動。
- 所有內部控制資訊在單一物件中可見。

缺點：

- F-02、F-03、F-04、F-05、F-07、F-08 的結構性失敗面仍存在。
- Prompt 必須持續同步 8 kinds、15 ops、11 evidence 與欄位矩陣。
- 新增任何 operation 都會擴大模型協定與 validator 的交叉複雜度。
- 以更多 prompt 說明修復個別錯誤，容易變成 one-example patch。

判定：可作為 rollback baseline，不建議作長期邊界。

## 18. Candidate Design B — Reduced Fixed Semantic IR

**定義**：減少欄位數，但仍要求每個回應使用同一固定 shape，例如 `intent/state/action/target/args/ids/reply`，無關欄位填 null/empty。

優點：

- 比 A 少 opcode 與 evidence 細節。
- Validator 與 prompt 改動幅度中等。
- 容易在 JSON mode 實作。

缺點：

- 仍保留 global null/empty matrix，F-02/F-03 只被縮小而未消失。
- READ、WRITE、CLARIFY、FREEFORM 的資料形狀本質不同，固定 IR 仍會產生不相關欄位。
- 未來擴充時容易重新長回 13-key contract。

判定：是可行的過渡方案，但不是最小錯誤表面的終局設計。

## 19. Candidate Design C — Discriminated Semantic IR

**定義**：第一層 `intent` discriminator 決定唯一 variant；各 variant 只允許相關欄位。模型輸出 semantic IR，application compiler 產生現有 internal decision。

建議 variants：

1. `read`
2. `change`
3. `clarify`
4. `freeform`
5. `abstain`
6. `target_not_found`

特性：

- 一般 variant 只需 2–7 個主要欄位；clarify 使用 4 個 top-level fields 加一個重用的 nested candidate。
- `MUTATE/PROPOSE/NOOP` 不再是模型政策選項，由 compiler 產生。
- Exact canonical operation 與 evidence token 不暴露給模型。
- 無關欄位不使用 null；直接不屬於該 variant。
- 本地 strict validator 仍 fail closed。
- Compiler 輸出格式與現有 internal engine 相容，DB schema 不變。

判定：**推薦**。它在不把自然語言判斷搬進 Python 的前提下，最大幅度降低重複編碼與非法組合。

## 20. Deterministic Compiler Option（Semantic IR v1 historical baseline）

Compiler 必須是純函式式、可完全離線測試的結構轉換層：

```text
provider JSON
  → strict Semantic IR parser
  → deterministic compiler
  → existing canonical TypedDecision
  → existing prepare / policy / proposal / commit / render engine
```

允許行為：

- enum-token canonical casing只適用於v1 protocol metadata，且最好直接拒絕非canonical值；它不適用於v2 source literal grounding，後者禁止case或任何其他normalization。
- `state_type + action` 查表成 internal operation。
- `basis + context` 查表成 internal evidence。
- 依 operation policy 產生 MUTATE/PROPOSE/NOOP。
- 建立 opaque clarification/proposal IDs。
- 從已保存的 active clarification 恢復相同 candidate context。
- 使用 DB 值 render READ 或 committed result。

禁止行為：

- 解析中文 copula、主詞或關鍵詞以改變模型意圖。
- fuzzy/substring/value-overlap 尋找 memory identity。
- 把錯誤 target 自動換成「看起來比較像」的 ID。
- 把 count 自動改 set，或反之。
- 為缺漏 args 補造值、item、field 或完整集合。
- 看到 destructive wording 就繞過模型 IR 自行建 proposal。
- 第二次 LLM 呼叫作 semantic repair／judge。

Compiler 對不完整或不相容 IR 的唯一安全結果是 validation error，且該 attempted turn 不改 conversation、current memory、history、proposal 或 clarification state。

## 21. Recommended LLM Responsibility

採方案 C 後，模型只保留以下無法由應用程式在不使用自然語言 heuristic 的情況下安全決定的責任：

- 判斷高階 intent：read/change/clarify/freeform/abstain/target-not-found。
- 判斷 typed state：scalar/set/count/record。
- 選擇 existing stable memory ID／history ID。
- 對 create 提供 semantic slot metadata。
- 從使用者明示內容抽取 args。
- 選擇較小 semantic action。
- 表達核准六值 evidence basis；例如完整列舉使用 `COMPLETE_ENUMERATION`、明示 delta 使用 `EXPLICIT_DELTA`、forget 使用 `FORGET`，item/field assertion 使用 `ASSERTION` 並由 action/args 區分。
- 判斷是否資訊不足，列出 missing semantic components。
- 只為 CLARIFY 產生 question，並只為真正 FREEFORM 產生 reply；其他 reply 原則上由 application 擁有。

模型不再負責 internal opcode spelling、internal evidence spelling、proposal policy、revision、history mutation、ownership、transaction、ID creation、clarification ID 或 deterministic reply rendering。

## 22. Recommended Application Responsibility

應用層應承擔所有可由已知結構與 committed state 決定的責任：

- provider envelope、JSON、union schema、additional properties、length、type、enum 驗證；
- action/state/args/basis compatibility；
- canonical operation/evidence derivation；
- destructive proposal policy；
- stable ID、ownership、user/session scope、revision 與 stale checks；
- create semantic key uniqueness；
- current/history/proposal/clarification authority separation；
- atomic persistence 與 rollback；
- confirm/cancel 0-call transitions；
- DB-backed READ rendering；
- mutation/proposal/noop/TARGET_NOT_FOUND/safe-ABSTAIN fixed responses；
- limits、firewall 與 fail-closed；
- logging 中記錄 raw IR validation outcome 與 compiler outcome，但不得洩漏 secrets。

「最大 application responsibility」不代表應用程式自行推理自然語言。界線是：已存在於 IR 或 DB 的結構資訊可 deterministic 處理；需要理解使用者語句的新語意不可由 heuristic 補上。

## 23. Deterministic Derivation Matrix

| Current model output／控制資料 | Application 可推導？ | Derivation inputs | Safety impact | 從 model protocol 移除？ | Notes |
|---|---|---|---|---|---|
| `kind` | 部分 | `intent`、compiled operation、no-change 結果、policy | 避免模型繞過 proposal；語意 intent 仍由模型負責 | 移除現行 `kind` | READ/CLARIFY/FREEFORM 等由 intent 映射；changed→semantic Proposal，NOOP→no-change |
| `state_type` | 否 | 使用者語意 | 應用不可用文字 heuristic 猜 | 保留但限 relevant variant | 只做 enum 與相容性驗證 |
| `operation` | 是 | `state_type + action + args shape` | 消除 invented token；非法組合仍拒絕 | 是 | 固定 lookup table |
| `evidence` | exact token 可推導 | `basis + intent/action + active context` | 保留 evidence gate，避免 payload 自動升格 | 移除 exact token | 精簡 semantic `basis` 仍由模型提供 |
| `memory_id` | create 可推導；existing target 不可 | create 用 DB allocator；existing 用 model `target_id` | stable ID 與 ownership 保持 application-enforced | 移除現行欄位，改 variant-local target | 應用不得 fuzzy 改選 target |
| `semantic_key` | 否 | Registry-v1 exact `slot_id` | 避免 free-text identity 回歸 | application-derived compatibility metadata | exact equality validation |
| `arguments` | 否（內容語意） | 使用者明示值/item/field/delta | 不得補造或修復 | 保留為 variant-local `args` | 應用驗證 shape/limits |
| `current_memory_ids` | 否 | model semantic selection | DB 驗證 ownership，但不保證 relevance | 保留於 READ | 改名 `current_ids` |
| `history_ids` | 否 | model semantic selection | 防止 current/history 混淆與越權 | 保留於 READ | lineage/type 由 DB 驗證 |
| `unknown` | 否 | model 判斷 personal-memory query 查無資料 | 與 ID 集合互斥驗證 | 保留於 READ | 應用產生 unknown reply |
| `clarification` | 包裝可消除；內容不可 | candidate、missing、question | 減少重複狀態；保留語意不確定性 | 移除現行 wrapper | 改 `clarify` variant |
| `clarification_id` | 是 | user + session + candidate + base revision | 防 stale／偽造／跨 session | 是 | application 產生 opaque ID |
| `display_label` | 否 | Registry-v1 exact lookup | 非lineage authority但versioned canonical metadata | application-owned | exact registry equality validation |
| `reply` | 視 intent | DB state、committed result、proposal/status template 或 model prose | DB truth 不被 raw prose 覆蓋 | 多數 intent 移除 | 原則上只在 FREEFORM/CLARIFY 保留 |
| proposal requirement | 是 | typed changed/NOOP result + `POLICY-18`；destructive effect另行衍生 | 模型不能直接提交任何changed Current | 是 | application決定changed→semantic Proposal或NOOP bypass |
| revision | 是 | current revision + valid committed transition | stale write fail closed | 不應進入 model protocol | transaction 內遞增 |
| history behavior | 是 | canonical operation + predecessor state | 保持 lineage 與 historical authority | 不應進入 model protocol | transaction 內 archive；rollback 原子化 |
| stable ID generation | 是 | scoped DB allocator | 防碰撞與文字 identity | 不應進入 model protocol | create only |
| rendering | 是 | validated IDs/proposal/committed DB values | 防矛盾與未提交值外洩 | 不應進入 model protocol | 只有真正 prose intent 由模型回覆 |
| ownership | 是 | authenticated user + DB row ownership | user isolation | 不應進入 model protocol | 不存在或越權一律 fail closed |
| atomic transaction | 是 | compiled action + DB transaction | 防 partial turn/state | 不應進入 model protocol | 任一寫入失敗全 rollback |

此矩陣直接回答哪些目前由模型填寫的資料其實是可推導的。所有 derivation 都來自結構化 IR、已驗證 DB state 或固定 policy，不從自然語言重新推理。

## 24. Failure-Surface Reduction Matrix

| Real failure | Semantic error | Serialization error | Duplicated-information error | Token-enum error | Policy-selection error | 方案 C 效果 | Semantic uncertainty 是否仍在 |
|---|---:|---:|---:|---:|---:|---|---:|
| F-01 Scalar CREATE → CLARIFY | 是 | 否 | 部分 | 否 | 否 | **降低但不消除**：create variant 較清楚，仍可能選錯 intent | 是 |
| F-02 incomplete/extra fixed decision fields | 否 | 是 | 是 | 否 | 否 | **消除該結構性類別**：variant 不要求 irrelevant keys，additional fields 拒絕 | 否 |
| F-03 READ 含 forbidden mutation/control fields | 部分 | 是 | 是 | 否 | 否 | **消除欄位混用**；若整體 intent 選錯仍存在 | 是 |
| F-04 invented `REPLACE_SCALAR` | 否 | 否 | 是 | 是 | 否 | **消除**：模型不再輸出 internal operation | 否 |
| F-05 NOOP empty reply | 否 | 是 | 是 | 否 | 否 | **消除**：NOOP acknowledgement 由 application 產生 | 否 |
| F-06 count-only input classified as Set | 是 | 否 | 是（state/operation/evidence 重複） | 部分 | 否 | **降低但不消除**：只選 state/action/basis；仍嚴格禁止 fabricated items | 是 |
| F-07 destructive action emitted as direct mutation | 部分 | 否 | 是 | 否 | 是 | **消除 policy 選擇類別**：application derived | 語意 action/target 仍在 |
| F-08 clarification ID/stale binding error | 否 | 是 | 是 | 否 | 否 | **消除**：ID/context application-owned | 否 |
| F-09 READ raw prose contradicts DB | 部分 | 否 | 是 | 否 | 否 | **既有 deterministic render 繼續消除權威衝突** | answer-mode/ID 選擇仍在 |
| F-10 create metadata 與 existing target 混用 | 部分 | 是 | 是 | 否 | 否 | **大幅降低**：create-only slot 與 target variant restrictions | 是 |

總結：可結構性消除 F-02、F-04、F-05、F-07、F-08；可顯著降低 F-03、F-10；F-01、F-06 與 READ relevance/answer-mode 仍是 model-semantic limitation。若 provider 只有 JSON mode，malformed JSON/union 仍由本地 fail-closed；未來 strict schema 是否可進一步降低失敗，需外部驗證。

## 25. Current vs Recommended Complexity

| 指標 | 現況 A | 建議 C |
|---|---:|---:|
| 每次模型 leaf fields | 固定 14 | 一般 variant 2–7；clarify 4 top-level + nested candidate |
| 全域 fixed decision fields | 13 | 0；改 per-variant |
| intent/kind variants | 8 | 6 |
| 模型需知道 internal operations | 15 tokens / 18 combinations | 0 |
| 模型 semantic actions | 隱含於 15 ops | 9 |
| 模型需知道 internal evidence | 11 | 0 |
| 模型 basis vocabulary | evidence 直接兼任 | 核准 6 值，且只在相關 change/clarify 出現 |
| irrelevant null/empty rules | 10 類以上 | 0 |
| destructive policy 選擇 | 模型選 | 0；application derived |
| clarification/proposal ID | 模型協定負擔 | 0；application generated |
| DB render authority | 已由 application 控制 | 保持 |
| DB schema migration | — | additive schema v6 nullable slot_id/registry_version/entity_id；legacy readable，no guessed backfill |

方案 C 的主要收益不是把 14 降成某個漂亮的單一數字，而是讓每一 variant 的欄位正交，移除 `kind × operation × evidence × defaults` 的交叉乘積。

## 26. Governance Impact

建議方案的**目標行為**可保留現有 invariants：stable ID、current/history/proposal authority、typed transition、revision、ownership、atomicity、fail-closed 與 firewall 都不變。然而，現行治理文字中若明定「DeepSeek 直接選 exact canonical operation/evidence/kind/clarification ID」，則責任邊界的文字必須先更新，不能把 compiler 改造當作純內部重構而略過。

本次 review 的影響盤點為：

- Affected invariants：`INV-01`–`INV-33`；Architecture D `INV-24`–`INV-26`，selective confirmation `INV-27`–`INV-30`，ontology/risk/benchmark `INV-31`–`INV-33`。
- Affected semantic contracts：全部68筆；Architecture D 9筆保持；新增8筆為`MSC-SEMANTIC-PROPOSAL-CREATE`、`MSC-SEMANTIC-PROPOSAL-CONFIRM`、`MSC-SEMANTIC-PROPOSAL-CANCEL`、`MSC-SEMANTIC-PROPOSAL-UNIFIED-DESTRUCTIVE`、`MSC-SEMANTIC-PROPOSAL-NOOP-BYPASS`、`MSC-SEMANTIC-PROPOSAL-STALE`、`MSC-SEMANTIC-PROPOSAL-CORRECT`、`MSC-SEMANTIC-PROPOSAL-COMMIT-IDENTITY`。
- Affected acceptance cases：canonical`Case #1`–`Case #20`語意oracle保持但write lifecycle改為proposal+Confirm；`AD-01`–`AD-20`保持；新增`SC-01`–`SC-20`。
- Affected implementation phases：現有gap plan的Architecture D phases保留，並新增Semantic Confirmation Phase 1–8；runtime須另案執行。
- Classification：**Architecture D + POLICY-18/19 governance reconciliation**。Architecture B typed engine保持；model-facing v2 grounding/claim-shape與downstream semantic-confirmation/immutable-payload gate已獲治理核准。

預期需要審議的治理變更：

- `MEMORY_SEMANTIC_CONTRACTS.md`：把 model output contract 從 exact internal decision 改為 Semantic IR；明訂 deterministic compiler、basis 與禁止 semantic repair。
- `MEMORY_ACCEPTANCE_SUITE.md`：外部可觀察行為不應改變，但測試證據應分成 IR validation、compiler、runtime；fixtures 不再假設模型直接輸出 internal opcode。
- `MEMORY_CONSISTENCY_SPEC.md`：核心 invariants 預期不需改義；若其中有 model-boundary wording，需同步術語但不得削弱 invariant。
- `MEMORY_IMPLEMENTATION_GAP_PLAN.md`：增加 IR/compiler migration phase、dual validation、feature flag/rollback 與 live conformance gate。

使用者已透過`POLICY-10`–`POLICY-22`解決Architecture D、grounding、registry-constrained IR、Count/Set authority、reply ownership、one-call、manual rollback、deterministic risk routing、selective confirmation、immutable proposals、schema v6 direction及frozen benchmark/STOP rule。Provider strict schema capability不是前置條件；local validators保留。

Production prompt、validator 或 runtime 仍須由後續明確授權的 implementation task 變更；本文件獲核准不等於本次已實作。

## 27. Compatibility and Migration

可保持相容的部分：

- memory IDs、history lineage、revisions、pending proposal/clarification lifecycle；proposal table只做additive metadata extension。
- user1/user2、session isolation、cross-session long-term memory。
- API/UI 的最終 observable behavior；browser 不需要知道模型 IR。
- Confirm/Cancel 與 clear-user endpoints。
- 現有 internal TypedDecision、prepare/commit/action classes，可作為 compiler target。

需要邊界適配的部分：

- system prompt 與 response schema。
- provider response parser。
- model-decision validator 前新增 Semantic IR validator/compiler。
- mock fixtures 與 contract-focused assertions。
- diagnostic logging 名稱與錯誤分類。
- proposal purpose/destructive/payload_version/semantic_key/display_label persistence、proposal-time CREATE final memory_id、deterministic rendering與Correct control。

不應直接讓新舊 payload 在同一 parser 中以寬鬆猜測兼容。過渡期應用 explicit protocol version 或 feature flag；收到不符合啟用版本的 payload 一律拒絕。Rollback 只切回完整舊 pipeline，不做欄位 heuristic conversion。

## 28. Architecture D and Semantic Confirmation Implementation Sequence (not executed here)

### Architecture D Phase 1 — Grounded IR v2 offline boundary

- 使用已核准且已同步的`POLICY-10`–`POLICY-22`作為boundary baseline。
- 定義 versioned Semantic IR v2 claim-shape schemas、structural validator、exact grounding validator、compiler contract及Count/Set same-ID transition。
- 以純離線fixtures建立IR/grounding/compiler/adversarial tests，diagnostics採privacy-safe metadata。
- Compiler目標仍是現有internal TypedDecision；changed output改交semantic proposal adapter；本phase不改DB、不改UI、不打DeepSeek。
- 驗證所有非法組合 fail closed，且沒有 NLP/regex/fuzzy semantic repair。

完成 gate：治理一致、`AD-01`–`AD-20`與`SC-01`–`SC-20`離線evidence完整、既有20-test行為基線仍通過；本治理任務不執行此phase。

### Architecture D Phase 2 — Mock integration 與 shadow comparison

- 在 feature flag 後加入新 prompt/parser/compiler。
- 對固定 mock/provider fixtures 同時比較「期望 internal decision」與 compiler output；不得以第二次 live LLM 呼叫做雙跑。
- 建立 protocol-version logging、錯誤 taxonomy 與 rollback 開關。
- 驗證失敗 turn 對 conversation/current/history/proposal/clarification 均無變更。
- 驗證所有changed candidates先經deterministic risk classification；auto only when every condition passes，otherwise immutable Human Review proposal；production proposal auto-confirm absent。
- 保持正式路徑使用舊 contract，直到 shadow/offline evidence 通過。

完成 gate：20 tests全通過、compiler mapping與proposal identity coverage完整、additive proposal migration已在explicit test DB驗證、rollback已演練。

### Architecture D Phase 3 — Controlled provider cutover

- **Phase 3B.1 prerequisite and manual checkpoints**：ontology constrained explicit literals改為model輸出`claimed_literal`，application unique-exact resolve並衍生authoritative offsets/slice。Zero/multiple occurrences fail closed；model offsets移除或只保留non-authoritative diagnostics；wrong-but-exact不修正。Phase 3B.1 offline及D1–D2 checkpoints已完成；既有D3 `五位`／`canonical_value=5`依narrow Count rule reclassify為`PASS AS SEMANTICALLY ACCEPTABLE`且不得為取得`五`重跑provider。D4現可由human執行；D4/D5完成前及另案授權前仍不得進Phase 4。
- 以目前已有證據的 JSON object mode + local structural/grounding validators實作；provider strict schema/tool capability不得阻擋 Architecture D。若未來外部確認可用，再作optional strengthening。
- 切換至 Semantic IR v2 prompt；Semantic IR v1只可由人工configuration/deployment操作切回，不能因單一turn失敗而automatic fallback或retry。
- 啟用deterministic Risk Engine routing；auto path須atomic，review path沿用local Confirm/Correct/Cancel；production auto policy在benchmark/另案enable前保持disabled。
- 先執行frozen ontology/risk held-out benchmark；只有go/no-go PASS後才可進Real40-v2或broader product tests。
- 成功後才將新路徑設為預設；觀察 invalid-schema、semantic-mismatch 與 fail-closed rate。
- 穩定期結束後才考慮移除舊 parser；移除需另行核准。

任何 phase 若出現治理矛盾、資料狀態差異或 compiler 無唯一 mapping，立即停止，不進下一 phase。

## 29. Automated Testing Strategy

維持整體 **恰好 20 個 automated tests**，不新增第 21 個。建議重整／強化既有測試內容而非增加 test method 數：

- IR schema/variant validation：涵蓋 exact keys、additional properties、missing fields、type/length/enum、malformed provider envelope。
- Compiler mapping：涵蓋 18 個 state-qualified canonical operations，可用 subTest 在既有 test method 中完成；驗證 9 semantic actions 的合法／非法組合。
- Evidence/basis mapping：六值 basis 對 complete set、target item、field/value、admitted delta、forget、continuation、insufficient 的唯一 mapping，以及 application-derived read selection/none。
- Risk routing：每個changed model-derived result須得到deterministic `AUTO_COMMIT_ALLOWED`或`HUMAN_REVIEW_REQUIRED`；auto須滿足全部條件，review才建立`SEMANTIC_CONFIRMATION` Proposal；模型無法直接commit。
- Proposal identity：rendered target/operation/operand/result/purpose/destructive/base revision與Confirm payload exact equal；stale/mismatch fail closed。
- Test-only proposal resolution：dedicated safe test DB、exact oracle、fixture user/session match；mismatch在Confirm前FAIL，production path不可達；與production risk auto route分離。
- Clarification：application-generated ID、same user/session 綁定、stale revision fail closed、continuation 不重新呼叫語意修復。
- READ：current/history/unknown、wrong ID、ownership、DB-rendered value。
- Failure atomicity：invalid JSON、invalid IR、compiler rejection、firewall、DB failure 均保持 conversation 與所有 memory state 不變。
- Regression：same-session、cross-session long-term memory、新 session 不繼承 short-term、user isolation、restart persistence、firewall、clear-user、Confirm/Cancel。

測試必須分別標示：

1. Semantic IR parser 的決定性驗證。
2. Compiler 的決定性映射。
3. Runtime/SQLite 的決定性狀態保證。
4. Mocked provider integration。

Mock success 不得報告為 real DeepSeek success；compiler coverage 也不得宣稱模型會永遠選對 intent/target/state。

## 30. Real40-v2 DeepSeek Conformance Lifecycle

先前14-call清單與Real40保留為broader product validation歷史；新release gate先執行frozen ontology/risk held-out benchmark。本次治理不執行任何call。只有benchmark PASS後，Real40-v2才依risk route驗證semantic extraction、auto atomicity或Human Review proposal exactness、final Current。

先前正交coverage分類如下：

1. scalar create
2. scalar set/update
3. scalar personal-memory read
4. set create with explicit complete state
5. set add named item
6. set remove named item → proposal
7. count create/set
8. anonymous event requiring clarify rather than fabricated set item
9. record set field
10. record delete field → proposal
11. unknown personal-memory read
12. ambiguous mutation → clarify with application-bound context
13. historical read
14. non-memory freeform

每個call只驗證一個主要semantic distinction；失敗不自動重試。應記錄raw provider JSON（排除secrets）、IR validation、compiler output、proposal oracle comparison、Confirm call count、runtime outcome與safe test DB before/after。Actual proposal任一target/create semantics、operation、canonical operand/result、purpose、destructive flag、base revision或user/session binding不符時，必須在Confirm前`FAIL — MODEL SEMANTIC`，Current不變。R05 wrong proposal`車 = 色。`不得auto-confirm；R21 fabricated Set在proposal前fail，exact Count 4→5才可auto-confirm。Live suite不取代deterministic20-test suite；Master100只在Real40-v2 PASS後執行。

## 31. Risks

1. **模型仍可能選錯語意。** Union schema 不能保證 scalar/set/count/record、target ID 或 intent 正確。
2. **`basis` 仍是模型輸入。** 它比 exact evidence token 簡單，但 complete-state 等判斷仍可能錯；application 只能檢查相容性。
3. **Provider capability 未確認。** 若只有 JSON mode，malformed union 仍由本地拒絕；strict schema 的收益需外部驗證。
4. **Compiler 可能被錯誤擴張。** 若未來加入 NLP/fuzzy fallback，就會重引入治理禁止的 semantic reconciliation；必須以 tests 和 code review 防止。
5. **雙協定過渡風險。** 寬鬆 auto-detect 會造成不明確解讀；必須 versioned/flagged，且 rollback 只能人工切換，不能 per-turn automatic fallback。
6. **Reply 行為可能有細微 UX 差異。** `POLICY-13` 已核准 application ownership；實作仍需以既有產品語意與核准安全文案為準，不可藉中央化改義。
7. **Prompt 簡化不等於語意提升保證。** 預期降低格式／token 失敗，但 F-01/F-06 只能以 live data 量測，不能先宣稱已解決。
8. **治理同步是前置條件。** 本次已完成`POLICY-10`–`POLICY-22` synchronization；未來若再改grounding、ontology、risk、benchmark、confirmation、proposal identity或user-visible semantics，仍需正式變更控制。
9. **Numeric provenance不是numeric proof。** Exact span只能證明source literal位置；`五 -> 5`等canonical numeric interpretation仍可能model-semantic wrong-but-structurally-valid。
10. **Risk/confirmation不是objective truth。** Human可確認錯誤；auto route則必須靠frozen zero-unsafe benchmark及deterministic restrictions控制。
11. **Schema v6 migration。** Add nullable `slot_id,registry_version,entity_id` to applicable Current/History/Proposal identity；legacy readable、no guessed backfill、no reinterpret old semantic_key；stable memory_id remains lineage authority。

## 32. Recommendation

採用 **方案 D + application-owned Canonical Slot Registry + deterministic Risk Engine + selective Human Confirmation**，並保留Architecture B typed-memory runtime與SQLite作為權威執行層。

推薦的精確邊界是：

- DeepSeek提供intent、canonical slot/UNKNOWN_SLOT、candidate entity/target、claim shape、operand semantic role與exact `claimed_literal`、ambiguity、model-semantic canonical numeric value與核准prose；不提供authoritative offsets。
- Application依序執行structure、unique exact literal resolution、authoritative span/slice derivation、grounding、registry resolution、family/op derivation、Architecture B preconditions、Risk Engine、auto atomic commit或Human Review proposal，以及IDs/revision/ownership/replies。
- User只確認Human Review exact rendered proposal；risk與confirmation均不構成objective semantic truth證明。
- 任何不具唯一 deterministic mapping 的 IR 直接 fail closed；不使用自然語言 heuristic、不做第二次 LLM repair。

Architecture D保留v1簡化protocol bookkeeping的收益，並對sourceable explicit literals增加application-owned unique-exact provenance gate及Count/Set single-authority規則。Wrong-but-exact literal仍可能通過provenance，因此它不承諾修復literal selection、claim shape、target或numeric interpretation等模型語意限制。

## 33. Approval Status

**狀態：`APPROVED_BOUNDARY_SIMPLIFICATION_PLAN`**

已核准：Architecture D、`POLICY-10`–`POLICY-22`、registry-constrained IR v2、exact grounding、Count/Set authority、Canonical Slot Registry、deterministic Risk Engine、selective Human Confirmation、immutable proposal identity、schema v6 direction、frozen benchmark/STOP rule、one-call policy及v1人工rollback限制。

本次工作已獲授權同步 governance/design 文件；仍未授權：

- 修改 production prompt、schema、validator、compiler 或 runtime；
- 修改 tests；
- 執行 paid DeepSeek call；
- 修改資料庫或進行 migration；
- 重建 ZIP。

`GOVERNANCE RECONCILIATION STATUS = COMPLETE`。既有Phase 1–3B成果保留；精確下一phase是另一個runtime task中的 **Phase 3B.1 — application-derived unique exact literal resolution**。該task只可調整ontology constrained diagnostic/model contract、resolver與tests；offline PASS後才可人工重跑D1，D1通過前不得D2或Phase 4。其後仍依compiler、Risk Engine、routing、offline benchmark harness、frozen held-out benchmark、go/no-go與only-after-PASS broader tests順序推進。Semantic IR v1只可作人工rollback path；legacy model-authored offsets可留在該legacy protocol，但ontology constrained IR內只有application-derived offsets具authority，resolution失敗不得automatic fallback。

`RUNTIME IMPLEMENTATION AUTHORIZED = YES, BUT ONLY IN A SEPARATE FUTURE IMPLEMENTATION TASK.`


## 34. Post-Benchmark Product Supersession — Human-Reviewed Memory Assistant

正式frozen run `freeze-v1.2-6fb6d482f9b2142c53ca`在ordinal 122的`HB-OFFICE-100`產生validated semantic mismatch且`unsafe_auto_commit=true`，已觸發`POLICY-22` STOP rule。故本文件先前所有「benchmark PASS後可另案production auto-commit」敘述，對**目前model/architecture**均被`POLICY-23` supersede。

目前production target固定為：

`one model call -> constrained ontology IR -> structural validation -> application unique-exact grounding -> Slot Registry -> deterministic compiler -> Architecture B authoritative preconditions -> deterministic Risk Engine guardrails -> HUMAN_REVIEW_REQUIRED -> immutable Semantic Confirmation Proposal -> explicit local Confirm/Correct/Cancel -> atomic commit`

Deterministic `NOOP`, `TARGET_NOT_FOUND`, `READ`, `CLARIFY`, `FREEFORM`, `ABSTAIN`, `UNKNOWN_SLOT` safe clarify/decline及fail-closed維持non-write。Risk Engine仍可產生reason codes與always-review判定，但目前product不得把任何model-derived changed write轉成production auto-commit。

Automatic path的freeze/result/evidence改為archive-only；不得重跑剩餘538 turns作為rescue，也不得以case-specific Prompt/parser修補後沿用同一freeze。若未來有materially new model/architecture，需先另案治理並建立全新freeze。

### Human-Reviewed product finishing phases

1. **HR-P1 — Governance + product hard lock/status**：標示Human-Reviewed product mode、server-side封鎖archived benchmark execution、production auto-commit status=false。
2. **HR-P2 — Production ontology shadow**：Normal Chat以真實Current建立server-owned slot/entity/target candidates，執行ontology pipeline但不建立Proposal；人工UI驗semantic selection/preconditions。
3. **HR-P3 — Proposal-only production cutover**：validated changed writes一律建立immutable Human Review proposal；NOOP/TARGET_NOT_FOUND/control保持non-write；無auto-commit。
4. **HR-P4 — Existing Confirm/Correct/Cancel integration**：使用既有local zero-call executors與schema v6 identity；驗stale/user/session/revision。
5. **HR-P5 — Manual UI acceptance**：至少CREATE、SET、COUNT、ADD、destructive REMOVE、NOOP、TARGET_NOT_FOUND、UNKNOWN_SLOT逐題人工驗證。
6. **HR-P6 — Final regression/package**：20/20 automated、protected DB hashes、restart/persistence、README/status/archive同步。

`HR-P1`後每個會改變Normal Chat行為的phase都必須先停下來讓使用者人工UI驗證，不可全部交由automated tests。
