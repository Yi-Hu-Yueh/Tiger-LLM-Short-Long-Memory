# 記憶一致性工程規格

狀態：`APPROVED_PROJECT_GOVERNANCE`（權威一致性規格）

本文件規範 Tiger Short/Long Memory 原型的應用層記憶一致性。除非本文件明確標示為「來源衍生原則」，其餘具體狀態、交易、識別與呈現規則均為本原型的「專案特定規則」，不得誤解為任何雲端服務或模型供應商的既有保證。

# 1. 目的與範圍

本規格是本專案記憶一致性的權威工程合約。所有未來涉及記憶行為的實作、測試與審查，MUST 先依本文件評估。

## 1.1 核准治理文件與權威分工

本專案的核准記憶治理集合為：

- `MEMORY_CONSISTENCY_SPEC.md`：一致性不變量與應用層安全規則。
- `MEMORY_SEMANTIC_CONTRACTS.md`：核准的語意狀態型別、mutation、證據、澄清與安全降級合約。
- `MEMORY_ACCEPTANCE_SUITE.md`：核准的 20 案例手動／語意驗收政策。

三份文件均為 `APPROVED_PROJECT_GOVERNANCE`。未來 memory-related 工作 MUST 在修改前完整讀取三者。若三者對 requested behavior 有未解決矛盾，MUST 停止；不得靜默選擇其中一份，不得修改 production code，必須先回報並取得使用者決策。明確核准的新政策必須先在三份治理文件中完成 reconciliation，才可另案實作；若 user-visible acceptance behavior 完全不變，reconciliation MAY 明確確認 `MEMORY_ACCEPTANCE_SUITE.md` 無需文字修改，而不是為同步形式強行改寫案例。

## 1.2 核准的 LLM → Application 邊界（POLICY-10 至 POLICY-23）

`POLICY-10` 核准 **Architecture C：Discriminated per-intent Semantic IR + Deterministic Compiler + Existing Typed Canonical Engine**，現作為Semantic IR v1歷史基礎與人工rollback path；`POLICY-16`進一步核准Architecture D Semantic IR v2並取代v1作未來production target。Semantic IR只存在於model-facing boundary；typed canonical state、stable `memory_id`、Current/History/Pending/Clarification權威層級、revision、transaction、rendering與SQLite persistence仍由既有Architecture B typed engine控制。`MEMORY_LLM_BOUNDARY_SIMPLIFICATION_PLAN.md`是此邊界的核准設計指引；它不得改寫本文件、語意合約或驗收套件的使用者可見行為。

`POLICY-11` 規定 DeepSeek 只提供真正需要語意理解的資訊：semantic intent、必要的 state type、需由語言理解選出的 target ID、semantic action、semantic arguments、必要的 semantic basis、澄清缺漏／措辭，以及真正 FREEFORM 的 reply。應用程式在 IR 完整且一致時，確定性編譯現有 internal kind、canonical operation、canonical evidence、NOOP-vs-semantic-confirmation-proposal policy 與固定 defaults。Compiler MUST NOT 讀取或重新解析原始自然語言、把 READ 改成 MUTATE、猜 target/value、fuzzy match slot、修復矛盾 intent、虛構 Set item，或把模糊事件轉成 Count arithmetic mutation。缺漏或矛盾 IR MUST fail closed，或依核准合約走模型明示的 CLARIFY；不得 semantic repair。

`POLICY-12` 核准 model-facing reduced basis vocabulary：`ASSERTION`、`COMPLETE_ENUMERATION`、`EXPLICIT_DELTA`、`FORGET`、`CONTINUATION`、`INSUFFICIENT`。Application MAY 只在 `basis + intent/action/arguments/context` 形成唯一安全 mapping 時，推導既有 internal evidence token；READ 可確定性推導 `READ_SELECTION`。若 mapping 不唯一，IR MUST 保留必要語意資訊或 fail closed，不得猜測。

`POLICY-13` 核准 application-owned deterministic replies：authoritative Current READ、受支援的 Historical READ、unknown-memory、成功 committed mutation、Pending Proposal creation、Confirm、Cancel、semantic NOOP/reassert、TARGET_NOT_FOUND，以及具安全固定文案的 ABSTAIN／validation fail-closed。DeepSeek prose 原則上只用於 FREEFORM 與 CLARIFY；任何例外必須由治理明確允許。集中 reply ownership 不得改變產品語意。

`POLICY-14`規定Architecture D boundary保持每個一般user turn至多一次DeepSeek call；typed Current/History/Clarification與stable `memory_id`保持有效。Schema方向由`POLICY-20` additive v6規範，不得bulk conversion或guessed backfill。舊13-key protocol只可作人工configuration/deployment rollback，不得per-turn retry/fallback、第二次call或silent repair。

`POLICY-15 — Exact Grounding of Explicit Literal Operands`：任何 Semantic IR operand 若由模型聲稱是目前 user turn 明示、且其 literal representation 可從 canonical current-turn text 直接取得，MUST 帶 exact source provenance。範圍至少包含 identity-bearing Set members、membership operands、explicit names、tags、device/project/person labels、explicit Scalar string values、explicit Record literal string values 與其他可直接取源的 literal values。Claim shape、semantic target selection、canonical state family、canonical field meaning、semantic action class 等必須由模型解讀的 semantic metadata 不要求逐字 grounding。對ontology constrained IR，模型提供semantic role與非空exact `claimed_literal`；application不得語意改寫該literal，並負責由original canonical current-turn text確定性衍生authoritative provenance。

Grounding 是 current-turn-local、deterministic、structural、exact、rejection-only。Application MUST以Python exact substring search計算`claimed_literal`在original canonical model-visible user-turn text（既有outer-whitespace handling後、任何Unicode normalization前）的全部exact occurrences。恰一個occurrence時結果為`RESOLVED_EXACT`，application衍生authoritative zero-based、half-open Python/Unicode-code-point `source_start/source_end`與exact slice；零個occurrence為`LITERAL_NOT_FOUND`並fail closed；多於一個occurrence為`LITERAL_AMBIGUOUS`並fail closed，絕不得自動選第一個。每個required literal獨立resolve；任一required operand未找到或不唯一，整個executable changed write fail closed，不得partial grounding。不得作 NFC/NFD/NFKC、case、punctuation、whitespace normalization，也不得tokenization、regex semantic inference、fuzzy/synonym/translation/alias matching、semantic normalization、NLP/keyword interpretation、inferred spans、prefix/suffix repair、model retry、second/judge model 或 external knowledge。

Ontology constrained IR的explicit literal operand SHOULD只帶model-selected `claimed_literal`，不要求模型計算authoritative offsets。若遷移期間仍接收model-authored `source_start/source_end`，它們只可作non-authoritative diagnostics，MUST NOT影響grounding acceptance；application-derived unique exact span是唯一authoritative provenance。若某claim shape同時需要model-interpreted canonical value與provenance，MUST明確區分source literal與semantic/canonical value，且不得把canonical transformation誤報為grounding已確定驗證。Grounding只證明model-selected literal唯一存在於current turn，不證明該literal在語意上選得正確；例如`我的車是白色。`中wrong-but-exact `色。`可為`RESOLVED_EXACT`但semantic correctness仍未證明。尤其source grounding只證明numeric claim的來源，不證明例如`五 -> 5`；未經另案治理核准的語言專用deterministic parser前，numeric interpretation仍是model-semantic limitation。

`CARDINALITY_ASSERTION`的narrow claimed-literal boundary如下：模型可選exact numeral token，或選由該numeral與其直接相連classifier構成的exact contiguous quantity phrase；例如同一已審核Count語意中的`五`或`五位`、`三`或`三個`、`兩`或`兩台`、`四`或`四隻`。所選literal必須保留由分離的model-semantic `canonical_value`表示的asserted cardinality；此等價性由model及human/preregistered semantic oracle負責，application不得解析classifier、判斷兩字串數值等價、剝除classifier、normalization、repair或改寫literal。此規則不允許任意周邊noun phrase，例如`五位成員今天`，亦不得泛化至Scalar/Record value boundary；R05的`色。`仍是因缺少material value meaning而產生的semantic-boundary error candidate。

任何 required grounding 失敗 MUST 在 compilation 前 fail closed：Current、History、revision、Proposal 及 failed-turn persisted artifacts 全部不變。Default diagnostics MUST NOT 包含 raw user text、raw operand values、source slices、API secrets 或 full IR payload；MAY 包含 protocol version、claim shape、operand count、occurrence count、span lengths、resolution status、PASS/FAIL 與 deterministic reason code。

`POLICY-16 — Registry-Constrained Grounded Claim-Shape Semantic IR v2`：核准 change shapes 為 `SCALAR_ASSERTION`、`CARDINALITY_ASSERTION`、`ENUMERATION_ASSERTION`、`MEMBERSHIP_ASSERTION`、`FIELD_ASSERTION`、`EXPLICIT_DELTA`、`FORGET`；control/intents 為 `READ`、`CLARIFY`、`FREEFORM`、`TARGET_NOT_FOUND`、`ABSTAIN`。不得重新建立舊 13-key protocol。對已知 ontology-managed slot，模型只負責 semantic intent、從 application 提供的 registry candidates 選擇 canonical `slot_id`（或明示 `UNKNOWN_SLOT`）、從 server-provided candidates 選擇既有 entity/target、claim shape、explicit operand semantic role與exact `claimed_literal`、genuine ambiguity，以及仍屬 model-semantic 的 canonical numeric interpretation。Application負責每個required literal的exact occurrence count、unique resolution status、authoritative `source_start/source_end`與exact source slice；offset counting不是模型責任。模型不得權威產生已知 slot 的 free-form `semantic_key` 或 `display_label`，也不得自創 `slot_id`、`entity_id` 或 registry entry。

Application 負責 registry/version validation、typed family與value type derivation、canonical `semantic_key`與`display_label` derivation、allowed-operation validation、exact grounding、Architecture B typed-state preconditions、deterministic Risk Engine、proposal/commit routing、`memory_id`與`entity_id` generation、Current/History/revision、transaction與deterministic replies。模型信心、prose或自報 risk 永不得授權 commit。

Semantic IR v1及其他legacy/manual rollback protocol MAY保留其既有model-authored offset contract；本次修訂不追溯改寫該人工rollback path。Ontology constrained IR同一protocol內不得存在dual authority：application-derived unique exact offsets是唯一authoritative provenance，model offsets至多為non-authoritative diagnostics。不得因resolution失敗automatic fallback至legacy protocol。

`CARDINALITY_ASSERTION` 只能進入 Count；`ENUMERATION_ASSERTION` 只能進入 Set 且每個 literal item 均須通過 `POLICY-15`；`MEMBERSHIP_ASSERTION` 只能進入 Set membership 且 explicit item 必須 grounded。Compiler MUST NOT manufacture identities。Production write boundary 的順序是：one DeepSeek call → constrained Semantic IR v2 slot/entity extraction → strict structural validator → exact source-grounding validator → Slot Registry resolution → deterministic claim-shape compiler與typed family/operation derivation → existing Architecture B typed-precondition resolver → deterministic Risk Engine → `AUTO_COMMIT_ALLOWED` atomic commit，或 `HUMAN_REVIEW_REQUIRED` Pending Semantic Confirmation Proposal → local Confirm/Correct/Cancel → atomic commit。Semantic IR v1 只保留為人工 rollback path，直到另案退役；不得 automatic fallback。

`POLICY-17 — Count and Enumeration Single Authority`：cardinality-only assertion 只建立或更新一個 Count lineage，不得產生 Set identities。Complete grounded enumeration 只使用一個 Set lineage，membership 為權威且 cardinality 確定性等於 unique items 的 `len(items)`，不得從同一 fact 建立平行 Count。Combined cardinality + complete enumeration 以 Set 為唯一權威；asserted count 必須等於 grounded unique-item count，否則整回合 fail closed，且不得另建 Count。

若模型選出 exact existing Count `target_id`、語意上選出 complete enumeration、每個 required literal item 均 grounded 且 target 無歧義，則 application MUST 先建立保留同一 `memory_id` 的 Count→Set `HUMAN_REVIEW_REQUIRED` semantic-confirmation Proposal。只有Confirm後，application才可在一個原子 transition 中把 Count Current 封存為 History predecessor，寫入 Set Current，revision 恰加1；不得建立平行Set lineage。此transition或confirmation gate未實作前只能fail closed或clarify。若existing Set接受後續count-only assertion，asserted count等於`len(Current Set)`時為deterministic NOOP；不相等時MUST CLARIFY，且不得建立獨立Count、擴張／收縮Set、虛構identities、增加revision、寫History或在澄清前建立Proposal。澄清reply ownership仍依既有application/model規則。

例：`讀書會有五位成員。` 是 cardinality claim → Count；`讀書會成員是 Alice、Bob、Carol。` 是 enumeration claim → grounded Set；`讀書會共有三位成員：Alice、Bob、Carol。` 是 combined assertion → 只建立 grounded Set，並驗證 declared count 與 unique item count 一致。`現在讀書會一共有五位成員。` 永不得產生 fabricated identities；若既有 Count=4，正確candidate是同一Count lineage的4→5。初始registry policy將`group.member_count`列為`HUMAN_REVIEW_REQUIRED`，只有Confirm後才更新Current為5、封存History predecessor=4並使revision +1。

`POLICY-18 — Risk-Classified Model-Derived Semantic Writes`：任何會實際改變 authoritative Current 的 fully validated model-derived candidate，MUST由application-owned deterministic Risk Engine產生且只產生`AUTO_COMMIT_ALLOWED`或`HUMAN_REVIEW_REQUIRED`。Default為`HUMAN_REVIEW_REQUIRED`；只有registry明示核准且滿足`POLICY-21`全部條件者才可`AUTO_COMMIT_ALLOWED`。Model-provided confidence、自報risk或prose不得成為authorization signal。

`AUTO_COMMIT_ALLOWED` write不建立semantic proposal；application在短SQLite transaction內原子寫入History（如適用）、Current、revision及成功回合，任一失敗整體rollback。`HUMAN_REVIEW_REQUIRED` write沿用完整Pending Semantic Confirmation Proposal與local Confirm/Correct/Cancel；Confirm前Current、History與revision完全不變。新的HARD application guarantee是：

> **NO MODEL-DERIVED SEMANTIC WRITE ENTERS CURRENT WITHOUT EITHER DETERMINISTIC LOW-RISK AUTHORIZATION OR EXPLICIT HUMAN CONFIRMATION.**

Proposal representation MUST 明確區分 `purpose=SEMANTIC_CONFIRMATION` 與 `destructive=true|false`，或使用同等明確的結構；semantic correctness confirmation 與 destructive authorization 是不同概念。對 destructive candidate，一個完整 rendered proposal 的一次 explicit Confirm MAY 同時表示「解讀正確」及「授權其效果」，不強制兩次連續確認。User-visible proposal、transaction-time revalidation、Cancel/Correct、scope/revision binding及零provider-call resolution仍依`POLICY-19`與`INV-28`–`INV-30`。

`NOOP`、`READ`、`TARGET_NOT_FOUND`、`ABSTAIN`、`FREEFORM`維持既有non-write behavior；`CLARIFY`在形成complete mutation candidate前不得建立semantic-write proposal。`UNKNOWN_SLOT`永不得auto-commit，只可進Human Confirmation的free-form/new-slot proposal、safe clarification或decline；任何registry self-modification均禁止。

`POLICY-19 — Immutable Semantic Proposal Payload Identity`：新的semantic-confirmation Proposal MUST持久化足以在不重讀原始自然語言、不重新呼叫模型、不重做target selection、不重建create-slot semantics/display metadata且不作semantic repair的情況下，唯一重建exact typed mutation的normalized canonical fields。共同identity至少包含`proposal_id,user_id,session_id,base_revision,purpose,destructive,payload_version,state_type,operation,arguments_json`及適用的lineage欄位；ontology-managed proposal另固定`slot_id,registry_version`及適用的`entity_id`。Legacy proposal的新增欄位維持NULL並只能走legacy executor，不得backfill或重新解讀。

Typed CREATE semantic proposal MUST在proposal creation時由application配置final stable `memory_id`並持久化；此時不改Current，Cancel後該ID永久不回收。CREATE的`target_memory_id` MUST為NULL，並持久化exact create `state_type`、operation、canonical `arguments_json`、registry-derived `slot_id/registry_version/entity_id/semantic_key/display_label`；Confirm不得產生不同identity、metadata、operation或arguments。Existing-target mutation以`target_memory_id`作authoritative lineage target；slot/entity metadata不得成為第二lineage identity。Stable `memory_id`仍是唯一authoritative lineage identity。

Semantic proposal render MUST只由同一persisted canonical payload確定性產生；Confirm MUST只從該payload加transaction-time authoritative state重建並執行。`display_text`只屬presentation/compatibility，`content`只屬legacy/compatibility，兩者不得替代canonical identity/arguments/operation/target。不得新增第二canonical `payload_json`或要求payload hash；`INV-28`由immutable fields、proposal identity、payload version、exact reconstruction、scope/revision binding與transaction-time revalidation執行。任何canonical proposal field不得in-place改義；Correct必須建立new `proposal_id`與new immutable payload，並取消／supersede舊proposal。

`POLICY-20 — Canonical Slot Registry and Entity Identity`：application MUST擁有immutable、versioned Canonical Slot Registry。每個`SlotDefinition`至少含`slot_id,entity_scope,typed_family,value_type,allowed_claim_shapes,allowed_operations,grounding_required,default_display_label,risk_class,auto_commit_allowed`。初始registry只含現有canonical acceptance/Real40所需的最小詞彙：`user.office.location`,`vehicle.color`,`pet.name`,`group.members`,`group.member_count`,`ownership.owner_profile.name`,`ownership.owner_profile.address`,`user.favorite_drink`,`user.birth_month`,`desk.floor`,`device.phone.model`,`person.residence.location`。`memory_id`是authoritative lineage identity；`slot_id`是versioned semantic property schema；`entity_id`是application產生的stable real-world instance identity。`first/second/third`等ordinal只能用來從server candidates解析，不得成為authoritative entity ID。

對ontology-managed新row，explicit `slot_id`是semantic schema authority，`semantic_key`是application-derived compatibility metadata且MUST等於canonical `slot_id`；`display_label`由registry/application產生。模型不得權威生成三者。Schema v6採additive nullable `slot_id`,`registry_version`,`entity_id`加入適用的Current、History與Proposal canonical identity；legacy row保持可讀，不得猜測backfill，亦不得把舊`semantic_key`自動重解讀成canonical slot ID。

Registry version `1` 的canonical metadata mapping固定如下；`semantic_key`在每列都等於exact `slot_id`：

| slot_id | display_label |
|---|---|
| `user.office.location` | `辦公室位置` |
| `vehicle.color` | `車輛顏色` |
| `pet.name` | `寵物名字` |
| `group.members` | `群組成員` |
| `group.member_count` | `群組人數` |
| `ownership.owner_profile.name` | `所有權人姓名` |
| `ownership.owner_profile.address` | `所有權人地址` |
| `user.favorite_drink` | `最愛飲料` |
| `user.birth_month` | `出生月份` |
| `desk.floor` | `書桌所在樓層` |
| `device.phone.model` | `手機型號` |
| `person.residence.location` | `居住地點` |

上述labels是Registry-v1資料，不得從`slot_id`文字演算法重建、runtime翻譯、由user prose推導、fuzzy/alias matching或要求模型生成。修改任一canonical label必須先做explicit registry-version/governance change。Entity-scoped rendering MAY在presentation層把entity名稱與generic slot label組合，例如`研究小組 — 群組成員`；entity名稱不得寫進`SlotDefinition.default_display_label`，其canonical value仍為`群組成員`。

`POLICY-21 — Deterministic Risk Engine and Selective Confirmation`：Risk Engine input為validated `slot_id`、entity scope、operation、claim shape、grounding result、typed-precondition result、registry version與slot risk policy；output為`AUTO_COMMIT_ALLOWED`、`HUMAN_REVIEW_REQUIRED`或既有non-write/fail-closed outcome。只有以下條件全部成立才可auto-commit：registry存在slot；slot/operation明示`auto_commit_allowed=true`；entity/target已知且無歧義；exact grounding PASS；non-destructive；無ontology extension；無state-family transition；無Count↔Set representation transition；typed preconditions PASS；無conflicting authoritative state；不需clarification；無unknown target/entity；application可atomic commit；slot-specific validation PASS。任一條件不成立，結果只能是`HUMAN_REVIEW_REQUIRED`或既有non-write/fail-closed outcome。

下列永遠要求Human Confirmation：`UNKNOWN_SLOT`、identity不確定的新entity、ambiguous target、destructive operations、`DELETE_MEMORY`,`REMOVE_ITEM`,`DELETE_FIELD`、Count↔Set transition、state-family transition、semantic correction、ontology extension、conflicting state、unsupported operation、record-schema uncertainty、entity ambiguity。初始benchmark-only低風險候選僅可為`user.office.location`,`user.favorite_drink`,`user.birth_month`；`pet.name`,`device.phone.model`,`desk.floor`僅可在held-out validation後另案提升。`vehicle.color`因R05 operand-boundary failure初始一律review；`group.member_count`因R21及Count風險初始一律review。任何slot不得僅因存在於registry而production auto-enable；production auto-commit在`POLICY-22`benchmark PASS及另案明確啟用前一律關閉。

`POLICY-22 — Frozen Ontology/Risk Benchmark and Project STOP Rule`：production auto-commit啟用前，MUST凍結model、model parameters、prompt、slot registry、registry version、risk rules、held-out dataset及evaluation procedure。DeepSeek v4 Pro MUST先在此constrained ontology下benchmark，尚不要求provider replacement；未來比較至少量測slot selection、entity/target selection、operand-span accuracy、claim-shape accuracy、protocol validity、unsafe auto-commit rate及Human Review rate。Held-out set至少含600個preregistered auto-eligible turns；unsafe auto-commit=0；forbidden-risk auto-commit=0；slot-selection error≤1%；operand/value error≤1%；protocol failure≤1%；overall Human Review rate≤35%；safe automatic completion rate≥65%。每個auto-eligible semantic error都必須被安全route至Human Review或deterministic non-write/fail-closed。

`POLICY-23 — Post-Benchmark Human-Reviewed Product Mode`：`POLICY-22`的STOP條件已在正式frozen run `freeze-v1.2-6fb6d482f9b2142c53ca`被觸發。Run在ordinal 122的`HB-OFFICE-100`產生`state=VALIDATED`、`benchmark_route=AUTO_ELIGIBLE`、`semantic_oracle_match=false`與`unsafe_auto_commit=true`，因此automatic semantic memory對目前model/architecture永久停止；剩餘538 turns不得為了平均掉此失敗而繼續，同一run不得以修改Prompt/parser/ontology/evaluator/dataset/threshold/risk rules後再續算。

在目前product baseline中，任何fully validated model-derived changed write，不論slot原先是否為benchmark candidate，production結果只能是`HUMAN_REVIEW_REQUIRED`，並在Commit前建立immutable `purpose=SEMANTIC_CONFIRMATION` Proposal。`AUTO_COMMIT_ALLOWED`只保留為歷史benchmark/未來新架構的抽象型別，不得是目前production可達結果。Deterministic Risk Engine仍可評估destructive、transition、conflict、unsupported、grounding與typed-precondition等guardrails並產生reason codes，但其production authorization上限是Human Review。Governed non-write結果仍不得被提升成Proposal。

重新追求automatic semantic memory只可發生於 materially new architecture or model，且必須先另案修改治理、建立新的freeze identity與held-out dataset/procedure，再執行新的benchmark；新實驗不得改寫、刪除或宣稱取代本次STOP evidence。Current product target正式改為`HUMAN_REVIEWED_MEMORY_ASSISTANT`。

`UNSAFE AUTO-COMMIT`指任何automatic committed mutation的`slot_id`、`entity_id/target`、operand/value/span interpretation、operation、會改變result semantics的claim shape、typed resulting state或authoritative mutation result任一錯誤；R05式slot family正確但value boundary錯誤亦屬unsafe。

> After the frozen ontology/risk benchmark, if ANY unsafe auto-commit occurs, any forbidden-risk write auto-commits, or at least 65% safe automatic completion cannot be achieved without weakening safety rules, the project MUST STOP pursuing automatic semantic memory and retain only Human-Reviewed Memory mode. The held-out dataset and thresholds MUST NOT be changed, thresholds relaxed, or ad-hoc prompt exceptions added after results are observed. A materially new architecture or model requires a separately approved evaluation.

上述政策延伸既有`INV-01`–`INV-23`，Architecture D使用`INV-24`–`INV-26`，selective confirmation與immutable proposal identity使用`INV-27`–`INV-30`，Slot Registry/Risk/benchmark使用`INV-31`–`INV-33`；既有不變量不重編。

本規格涵蓋：

- 短期對話上下文（Short-Term Conversation Context）
- 目前長期記憶（Current Long-Term Memory）
- 歷史記憶（Historical Memory）
- 待確認記憶提案（Pending Memory Proposal）
- 結構化記憶操作（Structured Memory Operations）
- 個人記憶查詢呈現（Personal-Memory Query Rendering）
- 使用者與 Session 隔離
- SQLite 持久化
- 失敗處理

自然語言模型的語意判斷具有機率性；應用程式 MUST 在可行處以確定性方式執行結構、權限、範圍、識別、版本、交易與輸出資料不變量。

本文件中的規範詞定義如下：

- **MUST／MUST NOT**：強制要求或禁止事項。
- **SHOULD／SHOULD NOT**：原則上應遵守；若偏離，必須有具體、可測試的工程理由。
- **MAY**：在不破壞其他不變量時可選擇實作。

來源衍生原則與專案特定規則的界線，於第 31 節明列。來源技術文件提供短期／長期、Actor／Session 範圍、記憶形成與整合、隔離及「記憶是資料」等設計原則；穩定 `memory_id`、Pending Proposal、確定性 SQLite 呈現等是本原型自行建立的一致性規則。

# 2. 非目標

本原型不企圖提供：

- 完美的自然語言理解
- 完美的語意實體解析
- Embedding 或向量搜尋
- 知識圖譜
- 企業級身分驗證
- 分散式鎖定
- 多節點一致性
- AWS 記憶服務
- DeepSeek 每一次語意選擇的自動正確性

目標是供 1–2 位使用者在單機使用的可靠本地原型。本專案不使用 AWS；所附 AWS 參考材料只支援一般工程原則，不構成本專案內部架構或供應商行為的描述。

# 3. 記憶狀態模型

## 3.1 短期對話上下文

短期對話上下文是 Session 範圍內的近期對話：

- MUST 以 `user_id + session_id` 為範圍。
- MAY 用於對話連續性、代名詞解析與任務延續。
- 不會僅因出現在對話中就成為權威持久狀態。
- New Session MUST NOT 繼承另一個 Session 的一般近期訊息。
- 本原型傳給模型的近期內容上限為最近六個使用者／助理回合（最多 12 則訊息）及約 12,000 字元。

## 3.2 目前長期記憶

目前長期記憶是已提交的使用者目前狀態：

- MUST 以 `user_id` 為範圍並持久化於 SQLite。
- 每筆記憶 MUST 有穩定 `memory_id`。
- 是目前已記住個人事實的權威資料來源。對 typed memory，canonical typed state 是權威值；`display_text` 不是第二份權威資料。
- 記憶身分 MUST NOT 由自由文字剖析器決定。
- 本原型採 hybrid typed canonical architecture：`ST-SCALAR`、`ST-SET`、`ST-COUNT`、`ST-RECORD` 使用 stable `memory_id` + typed canonical state + structured semantic operation；legacy free-text memory 以漸進方式繼續支援。
- `ST-RELATION` 在本原型 MUST 由 `ST-SET` membership 表示；不得建立另一個 first-class relation authoritative store。
- 本原型每位使用者最多 20 筆 Current Memory；legacy free-text 每筆仍最多 160 字元。

## 3.3 歷史記憶

歷史記憶是同一穩定記憶譜系先前提交過的版本：

- MUST 連結至該譜系的 `memory_id`。
- MUST 以 `user_id` 為範圍。
- 僅代表先前狀態，MUST NOT 被當成目前狀態。
- typed memory 發生實際 Current 變更時，History MUST 封存完整 typed predecessor state；legacy lineage 可保留原始 legacy content。
- 本原型保留每位使用者最近 10 筆歷史前身。

## 3.4 待確認記憶提案

Pending Memory Proposal 是具體但尚未確認的變更：

- MUST 同時以 `user_id` 與 `session_id` 為範圍。
- MUST 記錄建立時的 `base_revision`。
- MUST 恰好包含一個具體 `ADD`、`UPDATE` 或 `DELETE`。
- 只有Risk Engine結果為`HUMAN_REVIEW_REQUIRED`的changed candidate建立proposal；該proposal MUST明示semantic-confirmation purpose與independent destructive flag。
- MUST 保存 immutable proposal payload／version identity；target、typed operation、canonical proposed state／operand、purpose、destructive flag 與 base revision 在該版本存續期間不得修改。
- User-visible rendering MUST 完整且確定性地來自該 payload；display text 不是第二份權威 mutation。
- 在 Confirm 成功前不是權威目前狀態。
- Confirm 只在本地套用已儲存的操作；Cancel 只捨棄提案。
- Confirm 與 Cancel MUST 產生零次 DeepSeek 呼叫。
- Correct 若改變 proposed target/value/operand，MUST 建立新的 immutable payload 或 version identity；不得修改 previously confirmed payload。

## 3.5 Typed Canonical State 與原型限制

`POLICY-05` 核准 hybrid typed canonical architecture；`POLICY-06` 核准下列 prototype limits。

Typed canonical state 的核准安全／產品限制如下；超限 MUST fail closed，MUST NOT 靜默截斷，DeepSeek 輸出不得繞過驗證：

| State | Limit |
|---|---:|
| Current memories per user | `<= 20` |
| Scalar string value | `<= 160` Unicode characters |
| Set items | `<= 50` |
| Each set item | `<= 160` Unicode characters |
| Record fields | `<= 20` |
| Record field name | `<= 80` Unicode characters |
| Scalar record-field value | `<= 160` Unicode characters |
| Count | integer，`0 <= value <= 1,000,000,000` |
| Serialized typed canonical state | `<= 4096` UTF-8 bytes |

這些是 prototype limits，不是 enterprise-capacity requirements。DeepSeek 仍負責 intent、target `memory_id`、state type、semantic action、arguments 與 reduced basis／evidence sufficiency 的語意判斷；應用程式在有效 Semantic IR 之後負責 deterministic compiler、internal operation/evidence/policy derivation、validation、transition、History、revision、transaction 與 rendering。不得宣稱自然語言解讀已成為 deterministic。

# 4. 資料來源權威階層

針對「目前狀態」問題，權威順序如下：

1. 已完整驗證、由使用者 explicit Confirm exact rendered proposal、並在同一原子交易中成功提交的記憶操作；提交後其結果即成為目前長期記憶。
2. SQLite 中已提交的目前長期記憶。
3. Pending Proposal 是非權威、待確認狀態。
4. 歷史記憶只代表先前狀態。
5. 近期對話只提供上下文，MUST NOT 靜默覆寫已提交狀態。

| 狀態來源 | 對目前狀態的權威性 | 持久化 | Session 範圍 | 可直接回答目前狀態查詢 |
|---|---|---:|---:|---:|
| explicit Confirm 後成功提交的 exact proposal result | 是；提交後成為目前記憶 | 是 | 否，為使用者範圍 | 是 |
| Current Long-Term Memory | 是 | 是 | 否，為使用者範圍 | 是 |
| Pending Memory Proposal | 否 | 是 | 是 | 否；只能標示為待確認 |
| Historical Memory | 否；僅先前狀態 | 是 | 否，為使用者範圍 | 否；只可回答歷史問題 |
| Recent Conversation | 否；僅上下文 | 是，依訊息保存政策 | 是 | 否，不可取代目前記憶 |

核心不變量：

> **COMMITTED CURRENT MEMORY IS THE AUTHORITATIVE CURRENT STATE UNLESS A VALID CURRENT-TURN OPERATION IS COMMITTED ATOMICALLY.**

# 5. 穩定記憶身分

- `memory_id` MUST 由應用程式產生。
- `memory_id` 是目前記憶譜系的權威身分。
- `slot_id`是ontology-managed semantic property schema，`entity_id`是stable real-world instance identity；兩者均不能取代`memory_id` lineage authority。
- Ontology-managed `semantic_key`是application-derived compatibility metadata且等於canonical `slot_id`；legacy `semantic_key`不得被重解讀或以文字相等、近似或重疊作為lineage identity、merge、UPDATE或DELETE依據。
- `UPDATE` MUST 保留原 `memory_id`。
- 歷史列 MUST 保留同一 `memory_id` 譜系。
- `DELETE` MUST 以穩定 ID 指定目標。

應用程式 MUST NOT 以下列方式判定有效記憶身分：

- 正規表示式主詞剖析
- 中文繫詞或句型剖析
- 值重疊
- 子字串比對
- 語意字串差異比較
- Python 中的自由文字主詞推論
- 共享值

例如：Office 與 Home 即使都等於 Taipei，仍是兩筆不同事實；Research Group 與 Laboratory 即使都包含 Bob，仍是不同譜系；Owner Name 與 Owner Address 即使中文句子都含「有／在／是」，仍不得據此合併。

# 6. 結構化記憶操作

## 6.1 ADD

`ADD`建立新的穩定記憶譜系。模型提供candidate，application產生`memory_id`並derive registry metadata。只有Risk Engine=`AUTO_COMMIT_ALLOWED`才可直接原子建立authoritative lineage；otherwise建立`HUMAN_REVIEW_REQUIRED`proposal，Confirm前不得建立Current。

## 6.2 UPDATE

`UPDATE` MUST指向目前存在且屬於該user的`memory_id`。Changed candidate先經Risk Engine；auto route或Human Review Confirm成功時都MUST保留ID，並在同一atomic commit封存predecessor。

## 6.3 DELETE

`POLICY-07`：`DELETE_MEMORY` MUST 指向目前存在、且屬於該使用者的 `memory_id`。對 Scalar、Set、Count、Record，whole-memory DELETE 是 destructive operation，MUST 先建立具體 Pending Semantic Confirmation Proposal，且只可由本地 Confirm 提交；proposal明示`purpose=SEMANTIC_CONFIRMATION`與`destructive=true`，一次Confirm同時確認解讀與授權刪除。Cancel 保持 Current/History/revision 不變。成功 Confirm MUST 刪除該目前記憶及其連結歷史，且 MUST NOT 刪除無關譜系。一般 same-slot value replacement 是 `SET_VALUE`／對應 typed update，不得拆成 `DELETE_MEMORY + CREATE`。

## 6.4 NOOP

`NOOP` 表示持久記憶狀態不變。可用空 `memory_ops` 或唯一一個 `NOOP` 表示；不得與其他操作並存。semantic `REASSERT_NOOP` 不得建立 duplicate active slot、不得新增 History predecessor，且不得增加 revision。

## 6.5 操作集合驗證

操作套用前 MUST 對同一個回合前快照完整驗證：

- 未知 ID 必須拒絕。
- 其他使用者的 ID 必須拒絕。
- 同一目標的衝突操作必須拒絕。
- 重複 `ADD` 內容必須依目前結構規則拒絕。
- `DELETE` 後再以同一回合前內容重新 `ADD` 必須拒絕。
- 將一個譜系 `UPDATE` 成另一譜系的回合前內容必須拒絕。
- 所有操作套用後若產生重複目前內容，必須拒絕。
- 20 筆記憶、每筆 160 字元及操作數等限制必須強制執行。
- 任一無效操作集合 MUST fail closed，不得部分套用。
- Provider 只回傳 delta；未被有效操作指定的記憶 MUST 保持不變，不能因回應省略而被刪除。

# 7. 記憶形成與演化合約

本原型將語意記憶擷取／形成（extraction／formation）與記憶演化／整合（evolution／consolidation）分成模型判斷與應用控制兩層。

DeepSeek 的 model-facing Semantic IR 負責：

- 解讀自然語言語意。
- 表達 semantic intent、state type、target ID、semantic action、arguments 與 reduced basis；其中只有真正需要語意理解的欄位才由模型產生。
- 在資訊不足時表達 CLARIFY、缺漏 semantic slot 與澄清措辭。
- 為個人記憶查詢選擇相關穩定 ID。
- 只在 FREEFORM／CLARIFY 或治理明確允許的例外提供權威 user-facing prose。

應用程式負責：

- 以 deterministic compiler 將完整、一致的 Semantic IR 映射成既有 canonical internal kind、operation 與 evidence；不得 semantic repair。
- 依 typed precondition 先判定 candidate 是否實際改變 Current；所有 changed model-derived candidates 確定性建立 Pending Semantic Confirmation proposal，並獨立衍生 destructive flag；DeepSeek 不直接決定 `PROPOSE`、confirmation 或 commit。
- 驗證 ID、欄位與資料型別。
- 驗證使用者所有權及 Session 範圍。
- 驗證操作完整性、衝突與容量限制。
- 產生新記憶的 stable ID 與 clarification ID，並控制 replay/stale checks。
- 控制持久化、譜系、歷史、revision、Proposal/Clarification lifecycle 與交易。
- 從 SQLite 取得權威資料，並產生核准的 deterministic proposal rendering／acknowledgement／unknown/safe response。
- 絕不以啟發式語意修補模型輸出。

若 DeepSeek 產生不安全、矛盾、不完整或無效的 Semantic IR，應用程式 MUST fail closed，而非重新解讀、猜測其意圖、進行 automatic fallback，或為同一 turn 再呼叫 DeepSeek。

# 8. Pending Proposal 狀態機

狀態轉移如下：

```text
No Proposal -> Create Semantic Confirmation Proposal -> Pending -> Confirm OR Correct OR Cancel
```

**Create Proposal：** 只能在目標與結果具體、upstream validation通過、typed precondition會改變Current，且Risk Engine=`HUMAN_REVIEW_REQUIRED`時建立。建立提案可與成功對話回合一同持久化，但MUST NOT改變Current、History或revision；payload/version綁定完整rendered mutation。`AUTO_COMMIT_ALLOWED`不進入此state machine。

**Confirm：**

- MUST 產生零次 DeepSeek 呼叫。
- MUST 驗證 `user_id`、`session_id` 與 `proposal_id`。
- MUST 驗證 `base_revision` 仍等於目前 revision。
- MUST 驗證 proposal 仍 pending，重新讀取 authoritative Current，並重驗 typed preconditions。
- MUST 驗證 target identity、typed operation、canonical proposed state／operand、destructive flag、purpose 與 base revision 完全等於 confirmed/rendered immutable payload。
- MUST 套用該 exact stored operation，不得從對話重新推導、改 target/value 或重新呼叫 provider。
- typed Current 變更 MUST 封存完整 typed predecessor（如適用）；Confirm 實際改變 authoritative Current Memory 時 MUST 增加 revision。
- MUST 移除提案。
- 操作、revision、提案移除與確認訊息 MUST 在同一原子交易完成。

**Cancel：**

- MUST 產生零次 DeepSeek 呼叫。
- MUST 移除正確使用者／Session 的提案。
- MUST 保持目前記憶、歷史與 revision 不變。
- 提案移除與取消訊息 MUST 在同一原子交易完成。

**Correct：**

- 若 UI 可用 deterministic structured editing 完整表示 corrected target、typed operation、canonical value／operand 與 result，MAY 產生零次 DeepSeek 呼叫。
- Corrected proposal MUST 取得新的 immutable payload 或 version identity並重新render；舊 proposal不得靜默commit。
- Correct MAY 建立 replacement proposal等待Confirm，或以一個明確的 structured Correct-and-Confirm action同時確認當下完整rendered correction並commit；兩者都必須符合proposal/commit identity rule。
- 若 correction 是新的自然語言 semantic input，MUST 視為新 semantic turn，MAY 使用該 turn 唯一一次 DeepSeek call。
- Previously confirmed proposal payload MUST NOT 被修改或重用來提交不同 mutation。

**Stale Proposal：** revision、scope、pending status、payload identity 或 transaction-time typed precondition 任一不符時 MUST fail closed，MUST NOT 對已改變的記憶快照套用提案，且 MUST 保留提案供診斷或明確處理。

**Session 與清除：** New Session MUST NOT 繼承其他 Session 的提案；Clear User Data MUST 刪除該使用者所有提案。

# 9. Model-Derived Write Candidates 與 Semantic Confirmation

Model-derived candidate 只有在下列條件同時成立時，才可建立 Pending Semantic Confirmation proposal：

- 意圖明確。
- 目標無歧義。
- 最終持久狀態可精確決定。
- structural、grounding、compiler、firewall 與 typed precondition 全部通過。
- typed precondition 結果會實際改變 Current。

符合上述條件時 MUST 建立 semantic-confirmation Proposal，不得 direct commit；若目標或結果未知，MUST 詢問澄清且 MUST NOT 建立猜測性 Proposal。若 typed precondition 結果為 NOOP，MUST 使用 deterministic NOOP/reassert reply且不得建立proposal。

**Whole-memory DELETE policy：**對 Scalar、Set、Count、Record 的明確 whole-memory forgetting，只要 exact target 已知，MUST 建立 `DELETE_MEMORY` Pending Proposal，並只可由本地 Confirm/Cancel 解決。Confirm 提交刪除並增加 revision；Cancel 不改 Current/History/revision。一般值替換不是 DELETE。

**Record field policy（POLICY-09 + POLICY-18）：**`SET_FIELD` 是明確 replacement；當 target record、field、新值與結果均具體且無歧義時，changed candidate MUST 建立 semantic-confirmation Proposal。Confirm 必須保留同一 `memory_id`、封存完整 typed predecessor record，並因 Current 實際改變而增加 revision。`DELETE_FIELD` 是 destructive removal，也使用同一 semantic-confirmation Proposal；destructive flag必須明示，一次Confirm可同時完成semantic confirmation與destructive authorization。Proposal 建立不改 Current、不建 History、不增 revision；Confirm 以零次 DeepSeek 呼叫刪除 exact existing field、保留 record `memory_id`、封存完整 typed predecessor，並增加 revision；Cancel 以零次 DeepSeek 呼叫保持 Current/History/revision 不變。若 field 不明確或不存在，只能 clarification／`TARGET_NOT_FOUND`／safe abstention，mutation count為0且不得建立 guessed executable Proposal。刪除最後一個 field 的結果是同 lineage explicit empty Record `{}`，不是 `DELETE_MEMORY`；只有明確忘記整筆 record 才使用另行確認的 `DELETE_MEMORY`。

**匿名 count policy：**目前 `Reading club member count = 4`，使用者只說一位未具名成員離開時，即使可做 `4 - 1` 算術，也 MUST NOT 自動 `UPDATE` 為 3，MUST NOT 只根據該匿名事件建立 destructive executable Proposal。canonical mutation count 為 0；可澄清或型別化 non-execution。除非之後有有效且明確的 committed mutation，後續目前值查詢仍 MUST 呈現 4。使用者明確斷言新的 count（例如「目前人數是 3」）時，才可依一般 `SET_COUNT` 規則處理。

**Set mutation policy：**對已 admitted 的 named set／collection changed candidate，只要 exact collection、exact member／complete set 與 exact result 已知，MUST 建立具體 semantic-confirmation Pending Proposal；MUST NOT direct commit。Destructive removal的flag必須另行明示，但只需一次Confirm。Confirm 在本地套用，Cancel 在本地捨棄，兩者均為零次 DeepSeek 呼叫。若 OPTIONAL collection automation 未 admitted，可回傳明確 `FEATURE_NOT_ADMITTED` 並保持零變更。若 target 或 result 不具體，MUST 只澄清、mutation count 為 0，且 MUST NOT 建立 executable Proposal。明確、非破壞性的 member addition若會改變Current，同樣先建立semantic-confirmation Proposal；duplicate addition解析為NOOP時不建Proposal。

例：名冊為 Alice／Bob／Carol，使用者只說「一位成員離開」：無法知道是哪位，MUST 詢問澄清，MUST NOT 任意 `UPDATE` 名冊。

**Empty-set policy：**已知集合只剩 Alice，而已確認的 Proposal 要求移除 Alice 時，結果 MUST 是同一 stable lineage 的 explicit empty set `[]`；這是 `UPDATE`，前身依一般規則進入 History。集合變空不等於忘記集合。只有使用者明確要求 forget/delete 整個 collection fact 時才使用 `DELETE` 並依第 14 節移除整個譜系。

**Typed display policy（POLICY-08）：**typed canonical state 是權威資料。typed `display_text` MUST 在實務可行處由應用程式依 canonical state 確定性產生，MUST NOT 成為可與 canonical state 矛盾的獨立權威值。Legacy memory 可保留原始 legacy content。

# 10. 回覆與狀態一致性

任何面向使用者、聲稱個人持久狀態的文字，MUST NOT 與權威已提交目前記憶矛盾。

- 只有 explicit Confirm 後成功提交的 `UPDATE` 可描述操作後狀態；本原型使用固定確認文字避免模型陳述衝突。
- Proposal 的值是 pending，不是 current。
- 沒有提交變更時，目前長期記憶仍具權威性。
- 未解決的近期對話不會自動成為目前記憶。

確認過的失敗案例：

```text
目前 DB：讀書會成員數 = 4
近期對話：有人據報離開
未提交 UPDATE，亦未 Confirm Proposal
問題：現在有幾位成員？
```

系統 MUST NOT 將 3 呈現為已提交目前狀態；應以 SQLite 中的 4 為權威答案，或清楚區分尚未提交的敘述。

# 11. 確定性個人記憶查詢呈現

個人記憶查詢採安全讀取路徑：DeepSeek 只選擇相關的目前 `memory_id` 與歷史 `history_id`；應用程式驗證 ID 後，從 SQLite 取得實際內容。模型每類最多可選 5 個參照。

核心不變量：

> **ONCE A MEMORY ID IS SELECTED, THE AUTHORITATIVE VALUE COMES FROM SQLITE, NOT FROM LLM PARAPHRASING.**

## 11.1 僅目前記憶

呈現所選已提交目前記憶的精確內容；單筆使用「根據目前記憶：」，多筆清楚列示。

## 11.2 僅歷史記憶

呈現所選歷史列的精確內容，並明確標示為「先前記憶」。

## 11.3 目前與歷史

MUST 分別標示「先前記憶」與「目前記憶」，不得混為同一權威層級。

## 11.4 未知

沒有已提交且相關的個人記憶時，使用固定安全回覆：

```text
目前沒有相關記憶。
```

本規則不宣稱 DeepSeek 的語意 ID 選擇永遠正確；它只確保一旦選定並通過驗證，顯示值來自 SQLite，而非模型改寫。

# 12. 一般對話與個人記憶查詢

一般知識或普通對話 MAY 使用 DeepSeek 自由文字回覆；個人目前／先前狀態查詢 MUST 由儲存記錄提供權威值。

| 問題 | 路徑 |
|---|---|
| What is SQLite? | 一般 freeform 回覆 |
| What is my office location? | 目前記憶查詢 |
| What was my office location previously? | 目前／歷史記憶查詢 |

模型 MUST 在 Semantic IR 中明確路由為 FREEFORM 或相應 memory intent。記憶查詢不得與同一回合的 changed candidate／Proposal 結合；application 可推導 internal route，但不得把模型的 FREEFORM semantic intent 改寫為 mutation。

# 13. 近期對話規則

近期對話 MAY 協助：

- 解析代名詞或指涉。
- 延續同一 Session 的任務。
- 判斷是否需要澄清。

近期對話 MUST NOT：

- 在沒有已提交操作時覆寫 Current Memory。
- 自動成為 History。
- 自動成為權威持久狀態。
- 覆蓋已確認的 SQLite 狀態。

# 14. 目前與歷史語意

**Current** 是目前已提交狀態；**History** 是先前曾提交但已被同譜系 `UPDATE` 取代的狀態。

例：Office 依序由 Taipei 更新為 Hsinchu，再更新為 Taichung：

- Current：Taichung
- History：Taipei、Hsinchu
- 三者沿用同一 `memory_id` 譜系。

依本產品語意，`DELETE／Forget` MUST 移除目標目前譜系及其連結歷史；不得把被刪譜系的歷史留作可查個人記憶，也不得影響其他譜系。

# 15. 使用者隔離

每個記憶操作 MUST 以 `user_id` 為範圍，包括：

- 目前記憶讀取
- 歷史讀取
- `ADD`、`UPDATE`、`DELETE`
- Proposal 建立
- Confirm 與 Cancel
- Clear User Data

屬於 `user1` 的 `memory_id` MUST NOT 被 `user2` 讀取、更新、刪除、確認或取消，反之亦然。前端篩選不足以構成安全邊界；後端與 SQLite 查詢中的所有權驗證才是權威控制。

# 16. Session 隔離

- 近期對話 MUST 以 `user_id + session_id` 為範圍。
- Proposal MUST 以 `user_id + session_id` 為範圍。
- 長期 Current／History MUST 以 `user_id` 為範圍，可跨該使用者 Session 使用。
- New Session 保留同使用者長期記憶，但 MUST NOT 帶入舊 Session 的一般短期內容。
- Proposal MUST NOT 自動跨 Session；另一 Session 不得 Confirm 或 Cancel 它。

# 17. Revision 與過期快照安全

每位使用者具有 `memory_state.revision`。DeepSeek 對讀取時的快照推理；遠端呼叫期間不得保持 SQLite 寫入交易。

提交前，應用程式 MUST 在短寫入交易中比較 `expected_revision` 與目前 revision。若不相等，表示模型依據的快照已過期：

- MUST fail closed。
- MUST NOT 寫入部分對話或記憶。
- 呼叫者 SHOULD 重試整個回合。

Proposal Confirm同樣MUST比較`base_revision`。Revision表示committed authoritative Current version。只有`AUTO_COMMIT_ALLOWED`atomic commit或Human Review Confirm/Correct-and-Confirm實際改變Current才+1；read/clarify/proposal/cancel/NOOP/failure不增加。Clear只有實際移除Current才+1。現行runtime尚未實作registry/risk/selective routing，是待後續implementation對齊的gap。

# 18. 原子交易合約

模型／網路呼叫 MUST 發生在 SQLite 寫入交易之前。只有完整回應已通過 JSON、schema、操作、權限、firewall、答案路由及限制驗證後，才可開始短 `BEGIN IMMEDIATE` 交易。

一個建立 Pending Semantic Confirmation proposal 的成功聊天回合可在同一交易原子寫入：

- 使用者訊息
- 助理訊息
- immutable Proposal payload／version及其deterministic render

該聊天回合 MUST NOT 寫入 Current、History 或 revision。之後的 local Confirm／structured Correct-and-Confirm 必須在另一個短 `BEGIN IMMEDIATE` 交易中完成所有 transaction-time revalidation，並原子寫入：

- exact confirmed canonical mutation
- History predecessor／lineage change（如適用）
- Current state
- revision change
- proposal consume／status change
- application-owned confirmation message

任一資料庫寫入失敗時 MUST `ROLLBACK ALL`。不得在遠端 DeepSeek HTTP 等候期間持有寫入鎖。

核心不變量：

> **NO PARTIAL TURN MAY BECOME VISIBLE AS COMMITTED STATE.**

# 19. Fail-Closed 規則

代表性失敗包括：

- API 例外或供應商錯誤
- 無效 provider envelope
- 格式錯誤的 JSON
- 無效或缺漏 schema
- 無效 memory operation
- 未知 ID
- 其他使用者的 ID
- 操作衝突
- 記憶或輸入限制超出
- stale revision
- memory firewall 拒絕
- 資料庫寫入失敗

失敗回合的預期結果：

- Current Memory 不變。
- History 不變。
- revision 不變。
- Proposal 在該失敗路徑應保持原狀；不得誤建、誤刪或誤套用。
- 失敗回合的使用者與助理訊息均不得提交。
- 失敗的使用者訊息不得出現在下一次 DeepSeek 請求的近期上下文。

# 20. 空回覆規則

- 有效 changed candidate 先由 application 使用確定性文字 `待確認的記憶更新：<display_text>`；model-facing IR 不需提供 `reply`，且不得在此階段使用 committed-mutation acknowledgement。
- 只有 Confirm／structured Correct-and-Confirm 原子提交實際 Current mutation 後，application 才可使用固定確認文字 `記憶已更新。`。
- semantic `NOOP`／reassert 的 user-visible acknowledgement 由 application 確定性產生，不要求模型提供 `reply`；FREEFORM 搭配空 `reply` 仍 MUST fail closed。
- 記憶查詢模式可忽略模型 `reply`，由第 11 節的 SQLite 確定性呈現產生回覆。
- 空 `reply` MUST NOT 跳過操作、Proposal、答案路由或 firewall 驗證。

# 21. 記憶 Firewall

引用、文件、文章、逐字稿、日誌、程式碼、JSON／XML、Markdown 區塊、電子郵件及參考資料是資料，不是使用者個人狀態，也不是系統指令。

除非使用者的外層指令清楚地將其中資訊採納為自己的持久狀態，這些內容 MUST NOT 自動：

- 建立使用者記憶。
- 更新使用者記憶。
- 刪除使用者記憶。
- 建立 Pending Proposal。

記憶內容 MUST 被當成不受信任資料，不得提升成系統規則、權限授與或工具指令。Firewall 若拒絕模型提出的變更，整個回合 MUST fail closed。

# 22. 未知個人資訊

若沒有已提交且相關的個人記憶，系統 MUST NOT 猜測、從一般世界知識補足、或將近期未提交說法冒充為已知個人事實；MUST 使用安全未知回覆。此限制不影響一般世界知識的 freeform 回答。

# 23. Clear User Data

Clear User Data MUST 只移除目標使用者的：

- Conversations／Sessions／Messages
- Current Memory
- Historical Memory
- Pending Proposals
- 適用的 memory state／revision 狀態效果

本原型保留該使用者的 `memory_state` 列而非刪除共用 schema 狀態。只有Clear實際移除Current Memory時revision增加1；Current原已為空時，清Messages／History／Proposal不得增加revision。清除 `user1` MUST NOT 影響 `user2`，反之亦然。

# 24. 持久化與重新啟動

SQLite 狀態 MUST 跨程序重新啟動保存，包括：

- 目前記憶與穩定 ID
- 歷史記憶與譜系
- Pending Proposals
- revision 狀態
- 依現行實作保存的 Sessions 與 Messages

重新啟動 MUST NOT 重複執行已完成的資料遷移，MUST NOT 產生重複記憶、歷史或 Proposal。相同使用者／Session 應可恢復既有提案；其他 Session 不得看到它。

# 25. Migration 合約

- Migration MUST 可重複執行而不改變已完成結果（idempotent）。
- 破壞性 schema migration 前 MUST 建立 SQLite 備份。
- 一旦建立穩定 ID，後續 migration MUST 保留它。
- 舊資料若沒有可證明的譜系關係，MUST NOT 猜測映射；可保留於備份而不匯入不安全歷史。
- Migration 測試 MUST 使用使用者資料庫的副本，MUST NOT 對真實工作資料庫做探測性升級。
- 新增 schema 或欄位時，測試 MUST 證明既有 Current、History、revision、Sessions 與 Messages 的預期內容保持不變。
- 下一個核准schema方向為additive schema v6：在適用的Current、History與Proposal canonical identity加入nullable `slot_id`,`registry_version`,`entity_id`。Legacy rows保持可讀；不得猜測backfill，不得把舊`semantic_key`自動重解讀為canonical slot ID，且stable `memory_id`仍是authoritative lineage identity。

# 26. UI 一致性要求

本節只規範與記憶一致性直接相關的 UI 行為：

- Long-term Memory 面板 MUST 顯示 Current Memory，而非把 History 或 Proposal 混入目前狀態。
- Pending Proposal MUST 與 Current Memory 清楚區分。
- Pending 狀態只允許 Confirm／Correct／Cancel 解決；一般自然語言輸入與 Send 應停用。若提供 structured local Correct 控制，UI MUST 完整重繪新的 immutable proposal identity 後才可再次 Confirm。
- Proposal 在 Confirm 成功前 MUST NOT 顯示成已提交。
- Proposal MUST 完整顯示將提交的 canonical mutation、target、purpose、destructive effect 與 base revision；UI 顯示內容 MUST 與 Confirm 將提交的 immutable payload 完全一致。
- 對 `destructive=true` 的 semantic-confirmation proposal，一次 explicit Confirm 正常同時完成語意確認與破壞性授權；UI MUST NOT 無治理依據地要求第二次確認。
- 非目前可見 `user_id + session_id` 的遲到回應 MUST NOT 重繪另一個上下文。
- 每個非同步要求 MUST 保存發出時的使用者、Session、Proposal（如適用）及 request／context generation；只有仍匹配可見上下文時才可呈現結果或錯誤。
- 請求進行中 MUST 使用共享 guard 防止 Enter 與 Send 重複送出，並阻止切換上下文造成錯誤呈現。
- Confirm、structured Correct-and-Confirm 或 Cancel 成功後，輸入控制才可恢復正常聊天狀態。

# 27. 形式化不變量

1. **INV-01**：Current Memory 是目前持久狀態的權威來源；typed memory 以 canonical typed state 為權威值。
2. **INV-02**：穩定 `memory_id` 定義記憶譜系身分；`semantic_key` 若存在只屬 metadata，不能取代 ID。
3. **INV-03**：History 永不代表目前狀態；typed predecessor 必須封存完整 typed state。
4. **INV-04**：Pending Proposal 在 Confirm 前永不代表目前狀態，且 Proposal 建立不增加 revision。
5. **INV-05**：Recent Conversation 不得靜默覆寫 Current Memory。
6. **INV-06**：任何操作不得作用於其他使用者的 `memory_id`。
7. **INV-07**：`UPDATE` 保留 `memory_id`。
8. **INV-08**：`DELETE` 只移除指定譜系。
9. **INV-09**：無效狀態轉移一律 fail closed。
10. **INV-10**：已提交聊天回合具原子性。
11. **INV-11**：個人記憶呈現值來自通過驗證的儲存記錄；typed display 必須由 canonical state 確定性衍生且非獨立權威。
12. **INV-12**：未知個人事實不得被創造。
13. **INV-13**：引用／參考資料中的指令不得改變記憶。
14. **INV-14**：不得以自由文字剖析器定義記憶身分。
15. **INV-15**：未確認 Proposal 不得被描述為已提交目前狀態。
16. **INV-16**：未被 delta 指定的記憶不因 provider 省略而改變。
17. **INV-17**：模型呼叫期間不得持有 SQLite 寫入交易。
18. **INV-18**：過期 revision 的回合或 Proposal 不得部分提交；revision 只在 committed authoritative Current Memory 實際改變時增加。
19. **INV-19**：匿名成員事件不得自行對 count-only aggregate 產生 arithmetic mutation 或 executable Proposal；沒有有效 committed mutation 時 Current count 保持不變。
20. **INV-20**：named collection 的 destructive membership mutation 在目標與結果具體時必須先建立 Pending Proposal，並只可由本地 Confirm 套用；模糊 destructive mutation 只能澄清且不得建立 executable Proposal。
21. **INV-21**：移除集合最後一個已知成員的核准結果是同譜系 explicit empty set `[]` 的 `UPDATE`；`DELETE` 僅用於明確忘記整個 collection fact。
22. **INV-22**：destructive removal of committed authoritative typed state 必須經 Pending Proposal 與本地 Confirm 才可提交；包含 `REMOVE_ITEM`、`DELETE_FIELD` 與 Scalar／Set／Count／Record 的 `DELETE_MEMORY`。`DELETE_FIELD` 保留record lineage，最後field移除後為explicit `{}`，不得自動轉成`DELETE_MEMORY`。
23. **INV-23**：typed canonical state 必須遵守核准 prototype limits；超限一律 fail closed，不得截斷或由 provider 繞過。
24. **INV-24**：所有由模型聲稱為目前 turn 明示且可直接取源的 required explicit literal operands，其非空exact `claimed_literal`都必須依`POLICY-15`在current turn恰好出現一次；只有`RESOLVED_EXACT`可由application衍生authoritative exact span並進入compilation。`CARDINALITY_ASSERTION`的model-selected literal可為exact numeral token或exact contiguous numeral-plus-directly-associated-classifier quantity phrase，但application不得解析、剝除或修補classifier。`LITERAL_NOT_FOUND`或`LITERAL_AMBIGUOUS`使整個executable changed write fail closed，不得選first occurrence、partial ground，也不得留下任何authoritative或failed-turn persisted mutation artifact。
25. **INV-25**：Semantic IR v2 claim shape 限制 typed family：`CARDINALITY_ASSERTION` 只可為 Count，`ENUMERATION_ASSERTION` 只可為 grounded Set，`MEMBERSHIP_ASSERTION` 只可為具 grounded item 的 Set membership；application 不得製造 identity。
26. **INV-26**：同一 aggregate fact 的 Count 與 Set 不得成為平行 authoritative lineages。Grounded complete enumeration 以 Set 為唯一權威；核准的 Count→Set candidate必須先經semantic confirmation，Confirm後transition同`memory_id`、原子封存predecessor並只增加一次revision；Set後續count相等為NOOP，不相等則CLARIFY且零mutation。
27. **INV-27 — Selective Semantic Write Authorization**：任何 model-derived candidate 只要會實際改變 authoritative Current，MUST先取得deterministic Risk Engine的`AUTO_COMMIT_ALLOWED`或進入exact rendered `HUMAN_REVIEW_REQUIRED` semantic-confirmation proposal；沒有兩者之一時Current、History與revision MUST不變。
28. **INV-28 — Proposal/Commit Identity**：對`HUMAN_REVIEW_REQUIRED`路徑，Confirm實際提交的proposal/user/session/base revision、target或CREATE final `memory_id`、typed state/operation、canonical `arguments_json` operand/result、registry-derived `slot_id/registry_version/entity_id/semantic_key/display_label`、purpose、destructive flag與payload version MUST與persisted immutable payload及其render完全相同；CREATE identity/metadata不得在Confirm重新產生。任一 mismatch MUST fail closed。
29. **INV-29 — Local Resolution**：Confirm 與 Cancel MUST 使用零次 provider call；structured local Correct SHOULD 使用零次 provider call並產生新的 immutable proposal identity，無法安全結構化的自然語言 correction 必須成為新的 semantic turn。
30. **INV-30 — Confirmation Binding**：Semantic confirmation MUST 綁定 exact user、session、proposal identity 與 base revision；跨 user、跨 session、已 consumed、missing 或 stale proposal 一律不得提交。
31. **INV-31 — Slot Registry Authority**：ontology-managed write的`slot_id`、typed family、value type、allowed claim shapes/operations、canonical `semantic_key`、`display_label`與risk policy皆由指定registry version的application-owned `SlotDefinition`決定；模型不得自創或覆寫。`memory_id`維持lineage authority，`entity_id`與ordinal mention分離。
32. **INV-32 — Risk Default and Authorization**：Risk Engine是deterministic application function；default永遠是`HUMAN_REVIEW_REQUIRED`，model confidence永不得授權commit。只有`POLICY-21`全部條件通過且slot/operation明示auto-enabled才可`AUTO_COMMIT_ALLOWED`；otherwise human review或non-write/fail-closed。
33. **INV-33 — Unsafe Auto-Commit and Benchmark Stop**：production auto-commit在frozen benchmark PASS及另案明確啟用前禁止。任何unsafe或forbidden-risk auto-commit都觸發`POLICY-22` STOP rule，不得以修改held-out set、放寬threshold或ad-hoc prompt exception規避。
34. **INV-34 — Post-Benchmark Human-Reviewed Production Lock**：目前model/architecture已觸發`POLICY-22` STOP rule；production automatic semantic write MUST不可達。任何model-derived changed write若非deterministic non-write/fail-closed，MUST建立Human Review Semantic Confirmation Proposal並等待explicit Confirm。任何程式碼、feature flag、registry mutation、benchmark reuse或UI action若使目前架構恢復production auto-commit，即違反governance並須fail closed。

# 28. 驗收測試矩陣

| Scenario | Expected authoritative state | Expected visible behavior | Failure condition |
|---|---|---|---|
| 同 Session 上下文 | Current 不因一般對話自動改變 | 能延續近期對話 | 忘記同 Session 前文或把前文直接持久化 |
| 跨 Session 目前記憶召回 | 同 user 的 Current 保留 | 新 Session 可查到長期事實 | 需依賴舊 Session 訊息才能召回 |
| 重新啟動持久化 | Current／History／Proposal／revision 不變 | 重啟後可恢復正確狀態 | 遺失、重複或 migration 重跑污染 |
| 使用者隔離 | user1／user2 各自獨立 | 只顯示目前使用者資料 | 任一跨使用者讀寫或 ID 可操作 |
| Session 隔離 | 近期訊息與 Proposal 不跨 Session | New Session 無舊短期內容／提案 | 看到或操作另一 Session 提案 |
| 共享值的不同事實 | 各有不同 stable ID | Office/Home 等可同值並存 | 因共享 Taipei 或 Bob 被合併 |
| ADD | Risk判定前不變；`AUTO_COMMIT_ALLOWED`可原子建立新譜系，否則Proposal時不變、Confirm後建立；revision +1 | low-risk顯示application-owned成功回覆；其他顯示exact Pending Semantic Confirmation Proposal | 未授權commit、模型提供／偽造ID、換slot/entity或重複內容進入 |
| UPDATE | Risk判定前不變；`AUTO_COMMIT_ALLOWED`可原子更新，否則Proposal時不變、Confirm後同ID更新；前身進History、revision +1 | low-risk顯示application-owned成功回覆；其他先顯示exact proposal | 未授權更新、換ID、漏History或改錯譜系 |
| DELETE_MEMORY | Confirm 前不變；Confirm 後只移除目標 Current 與其 History，revision +1 | 先顯示 Pending Proposal，再本地確認 | direct delete、無關譜系或歷史被刪 |
| NOOP | Current／History／revision 不變 | application 顯示確定性 NOOP／reassert acknowledgement | 依賴空模型回覆、或任何記憶變更 |
| 多次連續 UPDATE | 每次risk resolution前不變；auto route原子commit，review route於Confirm後commit；前值依序為History | 每次依risk route顯示成功或exact proposal，之後可清楚查詢目前與先前值 | 未授權更新、History被當Current或譜系中斷 |
| Proposal 建立 | Current／History／revision 不變，immutable Proposal 存在 | 完整顯示 exact target、typed operation、canonical result、purpose、destructive flag 與 base revision | 建立即改 Current、無具體操作或 rendered/payload 不一致 |
| Confirm | 交易時重驗綁定、revision、Current、typed preconditions與payload identity；原子套用 exact proposal，實際改變 Current 時 revision +1並consume Proposal | 一次 Confirm 足以確認已完整rendered的semantic mutation；零模型呼叫 | 重新問模型、部分套用、錯 user/session、stale 或提交內容不同於顯示內容 |
| Correct | 未commit前建立新immutable proposal/version；或明確structured Correct-and-Confirm原子提交 | 結構化本地修正零模型呼叫；自然語言修正是新semantic turn | 靜默修改舊proposal、重用已確認identity或提交未完整rendered correction |
| Cancel | Current／History／revision 不變、Proposal 移除 | 固定取消，零模型呼叫 | 記憶變更或 Proposal 殘留 |
| Stale Proposal | 全部記憶狀態保持提交前狀態 | 顯示可處理的衝突錯誤 | 對新 revision 套用舊操作 |
| 未知個人事實 | 無新增記憶 | `目前沒有相關記憶。` | 猜測或用 freeform 偽造個人資料 |
| 文件提示注入 | Current／History／Proposal 均不變 | 安全拒絕該回合變更 | 文件文字建立操作或 Proposal |
| 原子 rollback | 交易前狀態完全保留 | 回報失敗 | 留下 user 訊息、History 或部分操作 |
| Clear User Data | 只清目標 user 全部相關狀態 | 該 user 回到空狀態 | 另一 user 受影響或 Proposal 殘留 |
| DB Current 與模型回覆矛盾 | DB Current 保持權威 | 顯示精確 DB 值 | 顯示模型矛盾數值 |
| Current／History 查詢 | 各自讀取所選 SQLite 列 | 清楚標示先前與目前 | 混淆層級或使用模型改寫值 |
| Provider 省略無關記憶 | 省略項目保持不變 | 無無關變化 | 將 delta 當完整快照覆蓋 |
| 其他使用者 memory ID | 所有狀態不變 | fail closed | 跨 user 讀取、更新或刪除成功 |
| 操作集合衝突 | 所有狀態不變 | fail closed | 同目標多操作或重複 final content 提交 |
| API／JSON／schema 失敗 | 記憶、訊息與 Proposal 均不變 | 安全錯誤 | 失敗 user 訊息出現在下一請求上下文 |
| Revision 競爭 | 較早快照不得提交 | 要求重試 | stale 回合覆蓋較新 Current |
| 匿名 count delta | Count 4 保持 4 | 澄清或型別化 non-execution | 自動變 3 或建立 destructive Proposal |
| 明確 destructive collection removal | Confirm 前 Current 不變；Confirm 後同 ID 更新並封存前身 | 顯示具體 Pending Proposal；Confirm/Cancel 本地處理 | 未確認即 direct commit |
| 最後成員移除 | Confirm 後同 ID 為 explicit empty set | 顯示空集合為目前狀態 | 將集合譜系 DELETE 或遺失 History |
| Record field replacement | 初始policy為HUMAN_REVIEW_REQUIRED；Proposal時不變，Confirm後SET_FIELD同ID更新、封存完整typed predecessor、revision +1 | exact且無歧義時顯示Pending Semantic Confirmation Proposal，再由本地Confirm | 未確認即commit、誤用DELETE_FIELD或遺失siblings |
| Record field deletion | Proposal時不變；Confirm後同ID移除exact field、封存完整predecessor、revision +1；最後field後為`{}` | Pending Proposal後本地Confirm/Cancel | direct delete、猜field、刪整筆record或把`{}`變DELETE_MEMORY |
| Typed limits | 超限時 Current／History／revision 不變 | fail closed，無截斷 | 超限 state 被提交或靜默截斷 |
| Read／Clarification／Reassert | Current／History／revision 不變 | 確定性 read、澄清或 NOOP | 產生 predecessor 或 revision 增加 |

# 29. 已知限制

應用程式無法保證 DeepSeek 永遠：

- 選到正確的記憶 ID。
- 完美選擇 `ADD`、`UPDATE`、`DELETE` 或 `NOOP`。
- 辨識每個含糊的自然語言意圖。
- 將一般對話與個人記憶查詢永遠正確分類。

本系統以穩定 ID、結構化操作、所有權與完整性驗證、Proposal、revision、fail-closed 交易及確定性 DB 呈現降低風險，但不宣稱達到完美語意正確性。固定字串呈現確保的是已選記錄的值一致，不保證「選哪一筆」必然正確。

`POLICY-18`的deterministic guarantee只保證model-derived semantic write必須先取得完整低風險授權或explicit human confirmation才會進入Current。Risk classification與confirmation都不證明objective semantic truth；因此production auto-commit必須先通過`POLICY-22` frozen benchmark。

R05 regression oracle：`vehicle.color`初始一律`HUMAN_REVIEW_REQUIRED`。對Current `車的顏色 = 白色`，若模型錯誤但結構有效地提出 `車 = 色。`，該candidate不得auto-commit且至多只能成為Pending Semantic Confirmation Proposal；Current、History與revision保持不變，使用者可Cancel或以structured Correct產生新proposal。只有完整顯示並確認正確canonical mutation後才可commit；slot family正確但value boundary錯誤若自動提交即屬`UNSAFE AUTO-COMMIT`。

R21 regression oracle：`group.member_count`初始一律`HUMAN_REVIEW_REQUIRED`。對Current Count `讀書會人數 = 4`，user輸入`現在讀書會一共有五位成員。`所產生的model-derived `SET_COUNT 5`，其exact claimed literal可為`五`或`五位`，只要human/preregistered oracle確認同一Count語意且application unique-exact grounding通過；兩者不因harmless numeral/classifier granularity而互判失敗。即使grounding、claim-shape與typed precondition均有效，也必須先成為semantic-confirmation Proposal；Confirm前Count仍為4且History/revision不變。

# 30. 變更控制規則

任何未來記憶行為變更 MUST：

1. 完整讀取三份核准治理文件並計算各自 SHA-256。
2. 指出受影響的不變量、語意合約與驗收案例編號。
3. 若語意改變，先同步更新三份治理文件。
4. 加入或強化回歸測試。
5. 保留所有未被明確修改的既有不變量。
6. 避免在 Python 新增自由文字語意啟發式。
7. 不得只為修正單一自然語言例子加入狹窄剖析器，除非該行為已被明確接受為產品政策。

Codex 或其他開發者 MUST NOT 只因一個對話例子失敗，就在未檢查本規格、權威階層與相關不變量的情況下修改記憶架構。

Canonical Slot Registry / Risk-Classified Semantic Writes governance reconciliation已完成。Runtime仍須獨立授權並依phase順序開始；第一個implementation phase只能建立Slot Registry types/config與static validation，不得在同一phase啟用routing、schema migration或production auto-commit。

# 31. 來源衍生原則與專案特定規則

| Principle | Origin |
|---|---|
| 短期與長期記憶分離 | 來源衍生：所附記憶技術參考資料 |
| Actor／user 與 Session 範圍 | 來源衍生：所附記憶技術參考資料 |
| Current／History 應區分 | 來源衍生原則 + 專案 Current／History 設計 |
| 記憶是資料，不是高優先權指令 | 來源衍生：所附安全與記憶污染技術資料 |
| 記憶擷取／形成與整合／演化需受應用治理 | 來源衍生：所附技術資料 |
| 使用者隔離、持久化、修正與刪除需明確處理 | 來源衍生工程原則 + 專案 SQLite 規則 |
| 應用產生的穩定 `memory_id` | 專案特定：Structured Memory v2／v3 設計 |
| `ADD／UPDATE／DELETE／NOOP` 精確驗證規則 | 專案特定：本原型結構化操作合約 |
| Pending Semantic Confirmation Proposal 與本地 Confirm／Correct／Cancel | 專案特定：本原型一致性設計 |
| SQLite 確定性個人記憶查詢呈現 | 專案特定：由手動失敗測試導出的安全規則 |
| revision 與 stale snapshot 拒絕 | 專案特定：本原型併發一致性設計 |
| fail-closed 原子回合 | 來源衍生工程原則 + 專案特定交易實作 |

Pending Proposal、穩定應用 ID、確定性 SQLite 呈現及本文件的精確交易規則，均不得描述成 AWS、DeepSeek、向量資料庫或其他供應商的內建功能。本原型不使用 AWS、Embedding、向量資料庫或知識圖譜。

## 31.1 參考依據（Reference Basis）

實際檢視的專案與參考材料如下：

- `技術文件/LLM 記憶系統完整技術報告.txt`
- `技術文件/long-short-term-memory.txt`
- `技術文件/[GenAI][AI Agents] Long-Term Agentic Memory With LangGraph - Introduction to Agent Memory - HackMD.mhtml`
- `技術文件/Day 10｜有了記憶才懂成長：Memory 讓 LLM 不再重蹈覆轍 - iT 邦幫忙__一起幫忙解決難題，拯救 IT 人的一天.mhtml`
- `技術文件/LLM 記憶煉金術：從短暫火花到永恆知識的進化之路｜深度解析長短期記憶機制、挑戰與未來應用.mhtml`
- `技術文件/System prompts for episodic memory strategy - Amazon Bedrock AgentCore.mhtml`
- 目前 `README.txt`
- 目前 `TEST_RESULTS.txt`
- 目前 `app.py`、`test_app.py` 與 `index.html` 所實作及驗證的行為

上述材料中的一般記憶概念用於來源衍生原則；本原型的狀態機、stable ID、Proposal、SQLite schema、revision、交易及呈現規則，以目前專案行為與本規格為準。
