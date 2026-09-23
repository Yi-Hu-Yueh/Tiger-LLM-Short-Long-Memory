# 記憶語意合約系統

## 1. Purpose

本文件定義核准的有限記憶語意合約系統：以「狀態型別 + 語意 mutation + 必要證據 + 合法結果」取代逐句提示修補。它是 authoritative semantic governance；production implementation 是否符合本文件，必須另案驗證與修正。

- 狀態：`APPROVED_PROJECT_GOVERNANCE`
- 合約數：76
- 狀態型別數：7
- 模糊類別數：7
- 安全降級規則數：7
- 覆蓋擴充情境數：42

## 2. Relationship to MEMORY_CONSISTENCY_SPEC.md

核准治理分工如下：`MEMORY_CONSISTENCY_SPEC.md` 管理一致性不變量；本文件管理語意狀態／mutation 合約；`MEMORY_ACCEPTANCE_SUITE.md` 管理權威驗收政策。本文件沿用 stable `memory_id`、Current/History/Pending 權威層級、user/session isolation、revision、原子交易、SQLite 確定性呈現及 fail-closed 規則。三者若出現未解決矛盾，必須停止實作、回報並取得使用者決策，不得靜默選擇。

本分析涉及 `INV-01` 至 `INV-33`。Mutation contracts 尤其涉及 `INV-01, INV-02, INV-03, INV-04, INV-05, INV-07, INV-08, INV-09, INV-11, INV-12, INV-14, INV-15, INV-16, INV-18`；隔離與交易覆蓋 `INV-06, INV-10, INV-17`；reference safety 覆蓋 `INV-13`；count/set/destructive/typed-limit safety 覆蓋 `INV-19` 至 `INV-23`；Architecture D exact grounding、claim-shape/type restriction 與 Count/Set single authority 覆蓋 `INV-24` 至 `INV-26`；selective confirmation、proposal/commit identity、local resolution與scope binding覆蓋 `INV-27` 至 `INV-30`；Slot Registry、Risk Engine及benchmark STOP rule覆蓋`INV-31`至`INV-33`；post-benchmark Human-Reviewed product lock覆蓋`INV-34`。

## 3. HARD / OPTIONAL / HARD SAFETY definitions

- **HARD**：已納入範圍時必須 canonical success；不得以降級代替。
- **OPTIONAL**：可自動化；若安全自動化未成立，允許明確的零變更降級。
- **HARD SAFETY**：即使功能 OPTIONAL，也禁止幻覺、任選目標、跨集合撤回、pending 洩漏、duplicate active slot、stale clarification 污染、虛構成員及 false-current claim。
- **DEFERRED**：自動化能力延後實作；其目前核准行為是零變更安全路徑，不表示政策尚待決定。

## 4. State Type taxonomy

| State Type | 定義 | 典型例 | Current free-text 適配度 | 建議 |
|---|---|---|---|---|
| `ST-SCALAR` | 一個 semantic slot 的單一 authoritative typed value | office、car color、pet name | 中；ID/History 安全，但 slot/value 仍由模型辨識 | `APPROVED HYBRID TYPED TARGET` |
| `ST-SET` | 有名稱且 item 唯一的 typed collection | research/lab members | 低至中；目前整個集合仍是單一字串 | `APPROVED HYBRID TYPED TARGET` |
| `ST-COUNT` | typed integer，不保存成員 identity | reading-club count | 中；目前數值在字串中 | `APPROVED HYBRID TYPED TARGET` |
| `ST-RECORD` | 同一 entity 下彼此獨立的 typed fields | owner.name、owner.address | 低；目前沒有 record schema | `APPROVED HYBRID TYPED TARGET` |
| `ST-RELATION` | subject-predicate-object 關係 | Bob MEMBER_OF Research | 目前應以 `ST-SET` 表示；沒有 relation storage | `REPRESENT THROUGH ST-SET`；本 prototype 不建 first-class relation store |
| `ST-PENDING` | 尚未 committed 的具體 typed Proposal；與 clarification 分離 | concrete REMOVE_ITEM proposal | concrete proposal 有 table；目前仍是 generic op/content | `APPROVED TYPED TARGET` |
| `ST-HISTORY` | stable lineage 的 committed predecessor | Taipei before Hsinchu | 高；目前只有 free-text payload | `APPROVED TYPED PREDECESSOR TARGET` |

`POLICY-05` 核准 hybrid typed canonical architecture：stable `memory_id` + typed canonical state + structured semantic mutation operation。Typed target涵蓋 Scalar、Set、Count、Record、必要的 Pending與History；legacy free-text gradual migration。`memory_id`仍是authoritative lineage identity；對ontology-managed row，explicit `slot_id`是versioned semantic property schema，`entity_id`是application-owned instance identity，`semantic_key`是application-derived compatibility metadata且等於canonical `slot_id`。`ST-RELATION`在本prototype繼續透過`ST-SET` membership表示，不建立first-class relation authoritative store。

依`POLICY-10`–`POLICY-23`，Architecture D v2中DeepSeek負責intent、從provided candidates選canonical `slot_id`或`UNKNOWN_SLOT`、existing entity/target selection、claim shape、explicit operand semantic role與exact `claimed_literal`、genuine ambiguity及仍屬semantic的numeric interpretation；application依序做structural validation、unique exact literal resolution、authoritative span derivation、exact grounding、Slot Registry resolution、typed family/operation derivation、Architecture B preconditions及deterministic Risk Engine routing。模型不得為known slot權威產生free-form `semantic_key/display_label`。不得把slot/entity/claim-shape/literal/numeric selection描述為deterministic，也不得把grounding、compiler、Risk Engine或Human Confirmation描述成semantic repair或objective semantic proof。

## 5. Mutation Algebra

有限 vocabulary：

- Scalar：`CREATE_SCALAR`, `SET_VALUE`, `DELETE_MEMORY`, `REASSERT_NOOP`
- Set：`CREATE_SET`, `ADD_ITEM`, `REMOVE_ITEM`, `REPLACE_SET`, `DELETE_MEMORY`, `NOOP`
- Count：`CREATE_COUNT`, `SET_COUNT`, `INCREMENT`, `DECREMENT`, `DELETE_MEMORY`, `NOOP`
- Record：`CREATE_RECORD`, `SET_FIELD`, `DELETE_FIELD`, `DELETE_MEMORY`
- Relation：`ADD_RELATION`, `REMOVE_RELATION`
- Control：`CLARIFY`, `PROPOSE`, `CONFIRM`, `CANCEL`, `ABSTAIN`, `TARGET_NOT_FOUND`, `NOOP`
- History：`ARCHIVE_PREDECESSOR`, `READ_CURRENT`, `READ_PREDECESSOR`

目前 wire schema 只有 `ADD/UPDATE/DELETE/NOOP`；上列 vocabulary 是語意層，不得宣稱全部已由 application typed operation 支援。

`POLICY-06` prototype limits：每 user Current `<=20`；scalar string `<=160` Unicode characters；set `<=50` items且每item `<=160` characters；record `<=20` fields、field name `<=80` characters、scalar field value `<=160` characters；count為integer且 `0..1,000,000,000`；serialized typed canonical state `<=4096` UTF-8 bytes。超限 fail closed且不得截斷。

`POLICY-07`：Scalar、Set、Count、Record 的 whole-memory `DELETE_MEMORY` 都是 destructive，必須先建立 concrete Pending Proposal，再由本地 Confirm/Cancel解決。一般 same-slot replacement不是DELETE+CREATE。Set final-member `REMOVE_ITEM` 結果仍是same-lineage `[]`，不是DELETE_MEMORY。

`POLICY-08`：typed canonical state是權威；typed display由application盡可能deterministic衍生且非獨立權威。Revision只代表 committed authoritative Current Memory version；只有Current實際改變才+1。Read、Clarification、Proposal creation、Cancel、REASSERT_NOOP、NOOP與所有失敗均不增加revision。

`POLICY-09`：Record `DELETE_FIELD` 是destructive removal，必須concrete Pending Proposal→local Confirm/Cancel。Confirm刪除exact existing field、保留record `memory_id`、archive完整typed predecessor，並因Current改變而revision +1；Cancel與Proposal creation不改Current/History/revision。Ambiguous或nonexistent field不得mutate或建立guessed proposal。Final-field deletion產生same-lineage explicit `{}`，不得轉成`DELETE_MEMORY`。Record schema uncertainty與initial `SET_FIELD` policy均為`HUMAN_REVIEW_REQUIRED`。

`POLICY-10`：核准 model-facing **discriminated per-intent Semantic IR + deterministic compiler + existing typed canonical engine**。Semantic IR 不取代本文件的 canonical operations、typed state 或 transition contracts；它是進入既有 internal protocol 前的最小 model-facing 表示。

`POLICY-11`：DeepSeek 不再輸出可由 application policy/structure 唯一推導的 exact internal kind、canonical operation、exact evidence token、PROPOSE-vs-direct-commit、固定空欄位、clarification ID、revision/history behavior 或 deterministic acknowledgement。Compiler 只可把已明示 semantic fields 查表映射成 internal protocol；不得重新解析原始語言、猜 target/value、fuzzy match、修復矛盾 intent、虛構 item 或推導匿名 count arithmetic。

`POLICY-12`：model-facing basis vocabulary 固定為 `ASSERTION`、`COMPLETE_ENUMERATION`、`EXPLICIT_DELTA`、`FORGET`、`CONTINUATION`、`INSUFFICIENT`。Application 只在 `basis + intent/action/arguments/context` 唯一決定 internal evidence 時映射；否則保留必要 semantic input 或 fail closed。

`POLICY-13`：Current/Historical read、unknown、committed mutation、Proposal creation、Confirm、Cancel、semantic NOOP/reassert、TARGET_NOT_FOUND，以及可用安全固定文案表達的 ABSTAIN/validation failure，均由 application deterministic render；model prose 原則上限於 FREEFORM 與 CLARIFY。此 ownership 轉移不得更改 contract outcome。

`POLICY-14`：Architecture D boundary redesign本身不改typed semantics或stable IDs。`POLICY-20`核准downstream additive schema v6方向，在適用Current/History/Proposal加入nullable `slot_id,registry_version,entity_id`；legacy rows保持可讀、無guessed backfill，舊`semantic_key`不得自動重解讀為canonical slot ID。每個一般user turn維持一次一般DeepSeek call；舊13-key protocol只能是人工rollback path，不能成為per-turn retry/fallback、第二次call或silent repair。

`POLICY-15 — Exact Grounding of Explicit Literal Operands`：任何模型聲稱由 current user turn 明示且可由 canonical current-turn text 直接取得的 literal operand，必須帶 exact source provenance。Identity-bearing Set members、membership operands、names/tags/device/project/person labels、explicit Scalar strings、explicit Record literal strings 與其他 sourceable literals 均在範圍；claim shape、semantic target、state family、field meaning、action class 等 semantic metadata 不要求逐字 grounding。模型提供semantic role與非空exact `claimed_literal`；application不得改寫它，並在outer-whitespace handling後、Unicode normalization前的original canonical current-turn text中以Python exact substring search計算全部occurrences。恰一個為`RESOLVED_EXACT`，application衍生authoritative zero-based half-open Python/Unicode-code-point offsets與slice；零個為`LITERAL_NOT_FOUND`；多於一個為`LITERAL_AMBIGUOUS`。後兩者皆整回合fail closed，絕不得選第一個或partial ground。

Ontology constrained IR的identity-bearing literal SHOULD只輸出`claimed_literal`；authoritative `source_start/source_end`、exact slice、occurrence count與resolution status均由application衍生。遷移期model offsets若保留，只可作non-authoritative diagnostics且不得影響acceptance。不得Unicode/case/punctuation/whitespace normalization、tokenization、regex semantic inference、fuzzy/synonym/translation/alias/NLP/keyword matching、prefix/suffix repair、retry或second/repair model。Grounding只證明model-selected literal的unique exact provenance，不證明literal selection semantic correctness；wrong-but-exact literal可grounding PASS。若另有canonical model-interpreted value，必須與source literal分離；例如`五 -> 5`仍是model-semantic。任何required grounding failure在compilation前fail closed，且Current/History/revision/Proposal/persisted failed-turn artifacts不變。Default diagnostics不得包含raw text/value/slice、secret或full IR。

只對`CARDINALITY_ASSERTION`，model-selected exact `claimed_literal`可為numeral token本身，或該numeral加上直接相連classifier的exact contiguous quantity phrase，例如`五`／`五位`、`三`／`三個`、`兩`／`兩台`、`四`／`四隻`。所選literal是否保留由分離`canonical_value`表示的同一asserted cardinality，屬model及human/preregistered semantic oracle責任；application只作unique exact grounding，不解析classifier、不剝除classifier、不normalize、不repair，也不把任意周邊noun phrase視為Count operand。此narrow rule不適用於R05；`色。`仍缺少material Scalar value meaning並維持semantic-boundary error candidate。

`POLICY-16 — Registry-Constrained Grounded Claim-Shape Semantic IR v2`：change shapes固定為`SCALAR_ASSERTION|CARDINALITY_ASSERTION|ENUMERATION_ASSERTION|MEMBERSHIP_ASSERTION|FIELD_ASSERTION|EXPLICIT_DELTA|FORGET`；controls/intents為`READ|CLARIFY|FREEFORM|TARGET_NOT_FOUND|ABSTAIN`。模型負責intent、provided registry中canonical `slot_id`或`UNKNOWN_SLOT`、provided existing entity/target selection、claim shape、explicit operand semantic role與exact `claimed_literal`、genuine ambiguity及model-semantic numeric interpretation。Application負責exact occurrence count、unique literal resolution、authoritative `source_start/source_end`與slice，以及registry validation、typed family/value type、canonical operation/evidence、`semantic_key/display_label`、allowed-operation validation、grounding、Architecture B preconditions、Risk Engine、proposal/commit routing、IDs、state與reply。Offset counting不是ontology model責任；known slot的free-form metadata、model offsets、model confidence或risk prose均非authoritative。

`POLICY-17 — Count and Enumeration Single Authority`：cardinality-only只有Count；complete grounded enumeration只有Set且cardinality=`len(unique items)`；combined assertion只有Set，且declared count mismatch整回合fail closed。Exact Count target後來收到complete grounded enumeration時，核准同`memory_id`的Count→Set candidate且一律`HUMAN_REVIEW_REQUIRED`；Confirm後才atomic封存Count History predecessor、寫Set Current並使revision +1一次，不得建立第二lineage；未實作前fail closed或clarify。Existing Set後來收到相等count是deterministic NOOP；不同count必須CLARIFY，且無Count、Set reshape、fabricated identities、revision、History或pre-clarification Proposal。

`POLICY-18 — Risk-Classified Model-Derived Semantic Writes`：新的HARD application guarantee是 **NO MODEL-DERIVED SEMANTIC WRITE ENTERS CURRENT WITHOUT EITHER DETERMINISTIC LOW-RISK AUTHORIZATION OR EXPLICIT HUMAN CONFIRMATION.** 每個fully validated changed candidate先由deterministic Risk Engine分類。`AUTO_COMMIT_ALLOWED`可跳過proposal並atomic commit；default `HUMAN_REVIEW_REQUIRED`必須建立`purpose=SEMANTIC_CONFIRMATION`的Pending Proposal，Confirm前Current、History與revision不變。Proposal另以`destructive=true|false`表示效果；一次完整rendered proposal的一次Confirm正常可同時確認semantic interpretation及destructive authorization。

Proposal payload與render identity MUST immutable，並綁定exact user、session、proposal identity、target／create semantics、registry-derived slot/entity metadata、typed operation、canonical operand/result、purpose、destructive flag與base revision。Confirm在零provider call下重讀Current並重驗全部binding、revision、typed preconditions與proposal/commit identity，然後原子commit；Cancel同樣零provider call且不改Current/History/revision。`NOOP|READ|TARGET_NOT_FOUND|ABSTAIN|FREEFORM`與incomplete `CLARIFY`維持non-write behavior。Production proposal auto-confirm禁止；`AUTO_COMMIT_ALLOWED`是獨立risk route，須先通過frozen benchmark並另案啟用。

`POLICY-19 — Immutable Semantic Proposal Payload Identity`：new semantic-confirmation proposal的canonical persisted identity使用normalized fields，不新增第二canonical `payload_json`且不要求payload hash。共同欄位為`proposal_id,user_id,session_id,base_revision,purpose,destructive,payload_version,state_type,operation,arguments_json`及適用lineage；ontology-managed proposal另固定`slot_id,registry_version`及適用`entity_id`。Typed CREATE在proposal creation時由application配置final stable `memory_id`，`target_memory_id=NULL`；registry metadata全部在Confirm前固定。Confirm只可從persisted payload與transaction-time authoritative state重建；Correct建立new proposal ID/payload。

`POLICY-20 — Canonical Slot Registry and Entity Identity`：application-owned immutable/versioned registry的`SlotDefinition`至少含`slot_id,entity_scope,typed_family,value_type,allowed_claim_shapes,allowed_operations,grounding_required,default_display_label,risk_class,auto_commit_allowed`。初始最小registry為`user.office.location`,`vehicle.color`,`pet.name`,`group.members`,`group.member_count`,`ownership.owner_profile.name`,`ownership.owner_profile.address`,`user.favorite_drink`,`user.birth_month`,`desk.floor`,`device.phone.model`,`person.residence.location`。`memory_id`是lineage authority；`slot_id`是schema；`entity_id`是application-owned stable instance identity；ordinal mentions只能解析provided candidates。Ontology-managed `semantic_key`由application derivation且等於canonical `slot_id`；`display_label`由registry/application擁有。

Registry-v1 exact `slot_id -> display_label` contract：`user.office.location -> 辦公室位置`；`vehicle.color -> 車輛顏色`；`pet.name -> 寵物名字`；`group.members -> 群組成員`；`group.member_count -> 群組人數`；`ownership.owner_profile.name -> 所有權人姓名`；`ownership.owner_profile.address -> 所有權人地址`；`user.favorite_drink -> 最愛飲料`；`user.birth_month -> 出生月份`；`desk.floor -> 書桌所在樓層`；`device.phone.model -> 手機型號`；`person.residence.location -> 居住地點`。這12個labels不得由模型、user prose、runtime translation、fuzzy/alias或slot文字演算法產生；label變更需要explicit registry-version/governance change。Entity-scoped presentation可另加entity name，但canonical generic label不含entity name。

`POLICY-21 — Deterministic Risk Engine and Selective Confirmation`：input為validated slot、entity scope、operation、claim shape、grounding result、typed-precondition result、registry version與slot policy；output為`AUTO_COMMIT_ALLOWED`,`HUMAN_REVIEW_REQUIRED`或既有non-write/fail-closed。Auto只在registry slot存在、slot/operation明示auto、target/entity known且unambiguous、grounding PASS、non-destructive、無ontology/state-family/Count↔Set transition、typed preconditions PASS、無conflict/clarification/unknown target、可atomic commit及slot-specific validation PASS時成立。任一失敗default human review。`UNKNOWN_SLOT`、uncertain new entity、ambiguity、destructive/delete/remove、representation/state-family transition、semantic correction、ontology extension、conflict、unsupported op、record-schema uncertainty永遠human review。初始benchmark-only候選是`user.office.location,user.favorite_drink,user.birth_month`；`pet.name,device.phone.model,desk.floor`僅可held-out PASS後另案提升；`vehicle.color`及`group.member_count`初始review。

`POLICY-22 — Frozen Ontology/Risk Benchmark and Project STOP Rule`：production auto-commit前凍結model/parameters/prompt/registry/version/risk rules/held-out data/procedure，先benchmark DeepSeek v4 Pro。至少600 preregistered auto-eligible turns；unsafe=0；forbidden-risk auto=0；slot-selection、operand/value、protocol failure各≤1%；Human Review≤35%；safe automation≥65%。`UNSAFE AUTO-COMMIT`是任何automatic committed mutation的slot、entity/target、operand/value/span、operation、semantics-changing claim shape、typed result或authoritative mutation result任一錯誤，包括R05 value-boundary錯誤。

`POLICY-23 — Post-Benchmark Human-Reviewed Product Mode`：正式freeze `freeze-v1.2-6fb6d482f9b2142c53ca`已在ordinal 122由`HB-OFFICE-100`觸發`unsafe_auto_commit=true`及mandatory STOP。因此本model/architecture的production changed-write contract不再允許`AUTO_COMMIT_ALLOWED` route；所有model-derived changed writes在structure/grounding/registry/compiler/Architecture B preconditions後，若非NOOP/TARGET_NOT_FOUND/control/fail-closed，MUST走`HUMAN_REVIEW_REQUIRED` → immutable Semantic Confirmation Proposal → explicit local Confirm/Correct/Cancel。Risk Engine保留為guardrail classifier與deterministic reason-code來源，不再對目前product授權auto commit。

此policy不宣稱Human Confirm等於objective semantic truth；它只恢復並強化HARD guarantee：**NO UNCONFIRMED MODEL-DERIVED SEMANTIC WRITE ENTERS CURRENT.** 任何materially new architecture/model若要重新評估automatic writes，必須另案治理與新的independent freeze；不得把本次失敗run重新標成PASS。

> After the frozen ontology/risk benchmark, if ANY unsafe auto-commit occurs, any forbidden-risk write auto-commits, or at least 65% safe automatic completion cannot be achieved without weakening safety rules, the project MUST STOP pursuing automatic semantic memory and retain only Human-Reviewed Memory mode. The held-out dataset and thresholds MUST NOT be changed, thresholds relaxed, or ad-hoc prompt exceptions added after results are observed. A materially new architecture or model requires a separately approved evaluation.

R05：`vehicle.color`初始review-required；wrong value boundary不得auto-commit。R21：`group.member_count`初始review-required；Count 4→5 candidate即使grounding/preconditions通過仍先proposal。

## 6. Evidence Model

| Evidence ID | 最低證據 | 不足時結果 |
|---|---|---|
| `EV-SLOT` | 一個 semantic slot 可辨識；同 lineage 存在時能選出正確 `memory_id` | `CLARIFY`／`TARGET_NOT_FOUND`／0 mutation |
| `EV-NEW-VALUE` | 新 scalar/count/field value 明確 | 0 mutation |
| `EV-SET-TARGET` | 唯一 named collection 已識別且存在 committed Current | `TARGET_NOT_FOUND` 或澄清 |
| `EV-ITEM` | 唯一 item 已明示；remove 時 item 當前存在；add 時 item 當前不存在 | contradiction 時 `NOOP`／澄清；不可猜 |
| `EV-COUNT-ASSERTED` | 使用者明確斷言目標 count | 可 `SET_COUNT`；否則不等同 derived delta |
| `EV-DELTA` | 方向、量、target 全明確，且不是只由匿名 membership event 推導 count | 匿名 member event 必須 `FEATURE_NOT_ADMITTED`／澄清；明確 asserted count 改走 `EV-COUNT-ASSERTED` |
| `EV-PROPOSAL` | 一個完整 immutable canonical mutation；exact user/session/proposal identity、base_revision、payload_version、target或CREATE final memory_id、typed state/operation、canonical arguments/result、CREATE semantic_key/display_label、`purpose=SEMANTIC_CONFIRMATION`、destructive flag與deterministic render identity | 不得建立 Proposal |
| `EV-CONTINUATION` | 回覆可唯一連結同 Session 最近尚未解決的 clarification | 否則視為新 request，不套用舊 intent |
| `EV-READ-REF` | 模型選出的 IDs 都屬當前 user snapshot | fail closed |
| `EV-EXACT-SPAN` | 每個required sourceable `claimed_literal`非空且在current turn恰一個exact occurrence；application-derived span為in-range、ordered、zero-based half-open code-point provenance，slice exact等於claimed literal | `LITERAL_NOT_FOUND`或`LITERAL_AMBIGUOUS`時整回合在compilation前fail closed；model offsets不具authority |

所有 mutation 還必須通過 ownership、revision、schema、limit、firewall、operation-set 及 transaction 驗證。

### 6.1 Model semantic input 與 application-derived internal protocol

下表適用於後續所有 contract rows。各 row 的 canonical operation 名稱描述 application internal contract，不表示 DeepSeek 必須逐字輸出該 token。

| Contract family | MODEL SEMANTIC INPUT | APPLICATION DERIVED INTERNAL OPERATION / CONTROL |
|---|---|---|
| Scalar | intent、canonical slot_id/UNKNOWN_SLOT、candidate target/entity、claim shape、grounded value、semantic numeric interpretation | application derives family/op/evidence/key/label/risk；auto commit only if all low-risk conditions, otherwise proposal；ID/revision/history/reply |
| Set | intent、canonical slot_id、candidate target/entity、claim shape、grounded items/item | application derives Set operations/evidence/risk；initial changed Set writes review-required；remove/delete destructive |
| Count | intent、canonical slot_id、candidate target/entity、cardinality claim、grounded numeric source plus semantic integer | application derives Count operations/range/policy/risk；anonymous event non-execution；`group.member_count`initial review-required |
| Record | intent、canonical field slot_id、candidate target/entity、field claim、grounded value | application derives Record family/field/op/risk；record schema uncertainty and initial Record writes review-required；siblings/history preserved |
| Read | read intent、relevant current/history IDs、unknown semantic selection | internal `READ`、`READ_SELECTION`、empty/default internal fields、0 mutation、SQLite rendering/unknown response |
| Clarification | clarify intent、candidate semantic context、missing slots、question、`INSUFFICIENT` 或 `CONTINUATION` | application-generated `clarification_id`、user/session/base_revision/expiry/status binding；non-authoritative lifecycle；0 mutation |
| Risk/Proposal/Confirm/Correct/Cancel | concrete validated changed candidate；Confirm/Correct/Cancel為local control | application Risk Engine selects auto or review；review path產生`SEMANTIC_CONFIRMATION` Proposal；Confirm/Cancel做scope/revision/replay/identity validation；structured Correct產生新identity；model不選risk、`PROPOSE`或commit |
| FREEFORM / safe status | freeform intent與reply；需要自然語言的clarification question | deterministic TARGET_NOT_FOUND/unknown/safe ABSTAIN/validation response；只有 FREEFORM/CLARIFY 原則上使用 model prose |

Architecture D 的 authoritative v2 pipeline 是：one DeepSeek call → Semantic IR v2 structural validator → exact grounding validator → claim-shape compiler → Architecture B typed-precondition resolver → Pending Semantic Confirmation Proposal → local Confirm/Correct/Cancel → SQLite commit。Semantic IR v1 只保留作人工 rollback，不能自動 fallback、retry 或觸發第二次 call。

### 6.2 Architecture D Grounding / Claim-Shape Contracts

下列 9 個合約加入既有 51 個合約，形成 60 個 stable semantic contracts：

| ID／名稱 | Required input / evidence | Deterministic result | Fail-closed / boundary |
|---|---|---|---|
| `MSC-GROUND-EXPLICIT-LITERAL` exact literal grounding | 模型為每個required sourceable operand選semantic role與非空exact `claimed_literal`；Count可選numeral或exact contiguous numeral+direct classifier quantity phrase | application exact-search全部occurrences；恰一個→`RESOLVED_EXACT`並衍生authoritative span/slice；不normalization、不剝除classifier；通過後才可compiler | model offset不具authority；wrong-but-exact只證明provenance、不證明semantic correctness；失敗零mutation |
| `MSC-CLAIM-CARDINALITY` cardinality claim | `CARDINALITY_ASSERTION`、semantic target、source provenance；numeric canonical value仍由模型解讀；human/preregistered oracle判斷numeral與numeral+direct classifier是否保留同一Count語意 | 只衍生 Count family；既有 Count 可 same-ID set/noop；application保留exact selected literal | 禁止 Set identities、classifier parsing/stripping及任意周邊noun phrase；`五 -> 5` 不因 span 而變 deterministic |
| `MSC-CLAIM-ENUMERATION` enumeration claim | `ENUMERATION_ASSERTION`、complete claim、每個 literal item grounded | 只衍生 Set family；unique membership authoritative，count=`len(items)` | 任一 item ungrounded 或 combined count mismatch 則整回合 fail closed |
| `MSC-CLAIM-MEMBERSHIP` membership claim | `MEMBERSHIP_ASSERTION`、exact target、grounded item、semantic add/remove action | 只衍生 Set membership op；任何changed add/remove皆走semantic Proposal，remove另標`destructive=true` | 禁止 compiler 製造 item、別名或跨集合 identity |
| `MSC-COUNT-SET-SINGLE-AUTHORITY` single truth | 同一 aggregate fact 的 claim shape、target 與 authoritative current family | cardinality-only→Count；complete enumeration/combined→Set only | 禁止平行 Count+Set authoritative lineages |
| `MSC-COUNT-TO-SET-REPRESENTATION` representation transition | exact existing Count ID、complete grounded unique enumeration、無 ambiguity、preconditions valid | 先建立semantic Proposal；Confirm後atomic same-ID Count Current→History predecessor→Set Current，revision +1 once | 未實作前 fail closed/clarify；禁止未確認transition或second lineage |
| `MSC-SET-CARDINALITY-NOOP` equal count reassert | existing Set + count assertion equal to `len(Current Set)` | deterministic NOOP；Current/History/revision不變 | 禁止另建 Count或 generic mutation acknowledgement |
| `MSC-SET-CARDINALITY-CONFLICT-CLARIFY` conflicting count | existing Set + count assertion differs from `len(Current Set)` | CLARIFY；Current/History/revision/Proposal不變 | 禁止 expansion/contraction、fabricated members、independent Count |
| `MSC-GROUND-FAIL-CLOSED` grounding rejection | empty/non-string required literal、`LITERAL_NOT_FOUND`、`LITERAL_AMBIGUOUS`或其他ungrounded operand | reject entire executable changed write before compiler；不得first-occurrence fallback或partial grounding；no Current/History/revision/Proposal/persisted failed-turn artifacts | diagnostics只允許protocol/shape/operand count/occurrence count/span lengths/PASS-FAIL/resolution status/reason code，不含raw values |

核准 mapping 例：

- Scalar replacement：model selects supplied `slot_id`/target and grounded value；application derives `SET_VALUE + EXPLICIT_ASSERTION`，再由Risk Engine選`AUTO_COMMIT_ALLOWED` atomic commit或`HUMAN_REVIEW_REQUIRED` proposal。
- Set removal：model IR `state_type=set, action=remove, target_id=m1, item=Bob, basis=ASSERTION`；application derives `REMOVE_ITEM + EXPLICIT_TARGET_ITEM + purpose=SEMANTIC_CONFIRMATION + destructive=true Proposal`。
- Count create：model IR `state_type=count, action=create, value=4, basis=ASSERTION`；application derives `CREATE_COUNT` 與相容的既有 internal evidence。若 evidence mapping 不唯一則拒絕，不得猜測。

### 6.3 Semantic Confirmation Contracts

下列8個stable contracts保留Semantic Confirmation fallback path。只有Risk Engine結果為`HUMAN_REVIEW_REQUIRED`時，changed candidate進入這些proposal contracts：

| ID／名稱 | Preconditions | Current / History / revision | Provider calls | Failure behavior |
|---|---|---|---:|---|
| `MSC-SEMANTIC-PROPOSAL-CREATE` review-required candidate提案 | candidate已通過schema、firewall、grounding、registry/compiler、ownership、limits與typed preconditions；Risk Engine=`HUMAN_REVIEW_REQUIRED`；exact scope/base revision；CREATE由app先配置final memory_id並備齊registry identity/state/operation/arguments | 持久化normalized immutable Pending Proposal與成功turn訊息；Current/History/revision不變；Cancel後ID不回收 | 一般semantic turn既有1次；proposal不增加call | 任一canonical field缺漏、驗證或DB失敗整回合rollback，不留下proposal或failed-turn artifacts |
| `MSC-SEMANTIC-PROPOSAL-CONFIRM` 本地確認 | exact active proposal；user/session/identity/base revision/Current/preconditions/rendered payload全部匹配 | 一個短交易原子寫History（適用時）、exact Current result、revision +1並consume proposal | 0 | missing/stale/mismatch/DB failure fail closed；不partial commit且proposal依交易結果保留 |
| `MSC-SEMANTIC-PROPOSAL-CANCEL` 本地取消 | exact active proposal且user/session/identity匹配 | proposal取消／移除；Current/History/revision不變 | 0 | missing或scope mismatch回`TARGET_NOT_FOUND`/fail closed；不得mutation |
| `MSC-SEMANTIC-PROPOSAL-UNIFIED-DESTRUCTIVE` 統一破壞性確認 | changed candidate且`destructive=true`；render完整呈現semantic mutation與destructive effect | Confirm前不變；一次Confirm後按exact proposal原子commit並revision +1 | proposal turn沿用1次；Confirm 0 | 禁止double-confirm依賴、未確認delete/remove或把destructive flag當purpose |
| `MSC-SEMANTIC-PROPOSAL-NOOP-BYPASS` NOOP繞過 | typed precondition證明canonical result等於Current | Current/History/revision不變；不建立Proposal | 不增加call | 禁止generic mutation acknowledgement、fake History或空proposal |
| `MSC-SEMANTIC-PROPOSAL-STALE` stale拒絕 | base revision、Current fingerprint/preconditions、scope或identity任一不再匹配 | Current/History/revision不變；舊proposal不得commit | 0 | deterministic stale conflict；不得重問模型、rebase或部分套用 |
| `MSC-SEMANTIC-PROPOSAL-CORRECT` 本地修正 | structured typed edit可安全表達；exact scope與未commit proposal | 舊proposal不commit；建立new proposal_id與完整immutable payload；舊CREATE memory_id不得回收；若明確Correct-and-Confirm則只commit完整rendered新payload並revision +1 | structured 0；自然語言correction是新turn且最多該turn既有1次 | 禁止in-place改canonical fields、隱性semantic repair或讓舊Confirm token套用新內容 |
| `MSC-SEMANTIC-PROPOSAL-COMMIT-IDENTITY` 顯示／提交同一性 | Confirm所見render由exact persisted normalized payload產生；CREATE含final memory_id及registry-derived slot/entity/key/label，existing target含authoritative target_memory_id | rendered payload = persisted payload = committed typed mutation；只加deterministic transaction-time validation及History/revision效果；不得再生identity/metadata/arguments | 0 | 任一render/payload/commit mismatch整筆fail closed；Current/History/revision不變；不得以display_text/content/hash替代canonical fields |

### 6.4 Ontology and Risk Contracts

下列8個stable contracts形成Canonical Slot Registry、selective routing與benchmark safety boundary：

| ID／名稱 | Preconditions | Deterministic result | Forbidden behavior |
|---|---|---|---|
| `MSC-ONTOLOGY-REGISTRY` registry authority | specified registry version；canonical slot exists | application derives family、value type、allowed shapes/ops、semantic_key=slot_id、Registry-v1 exact display label、risk policy | model-authored known-slot metadata；runtime label translation/algorithmic derivation；unknown version；registry mutation |
| `MSC-ONTOLOGY-ENTITY` entity identity | server-provided candidates or application-created stable entity_id；scope unambiguous | target uses stable entity_id independently of slot_id/memory_id | ordinal text as ID；model-created ID；cross-entity mutation |
| `MSC-ONTOLOGY-UNKNOWN` unknown slot | model returns `UNKNOWN_SLOT` or slot absent from registry | Human Review free-form/new-slot proposal, safe clarification, or decline | auto-commit；silent registry extension；guessed slot mapping |
| `MSC-RISK-CLASSIFY` deterministic classification | validated registry/grounding/preconditions and all required inputs | exactly `AUTO_COMMIT_ALLOWED`, `HUMAN_REVIEW_REQUIRED`, or existing non-write/fail-closed | model confidence/risk prose as authorization；missing-input auto route |
| `MSC-RISK-AUTO-COMMIT` low-risk atomic path | every `POLICY-21` low-risk condition PASS and production policy separately enabled after benchmark | no proposal；one short atomic commit of turn/History/Current/revision；application-owned reply | partial commit；write transaction across provider call；auto before benchmark/policy enablement |
| `MSC-RISK-HUMAN-REVIEW` fallback path | any low-risk condition fails or class is always-review | immutable Semantic Confirmation proposal; Current/History/revision unchanged until Confirm | direct commit；proposal auto-confirm；downgrade destructive or ambiguous risk |
| `MSC-RISK-UNSAFE-AUTO` unsafe metric | automatic committed mutation evaluated against frozen oracle | any wrong slot/entity/target/operand/span/op/semantic claim shape/typed result/authoritative result counts unsafe | excusing R05-style boundary error because slot family was correct |
| `MSC-BENCHMARK-FROZEN-STOP` frozen gate | preregistered ≥600 auto-eligible turns; frozen model/parameters/prompt/registry/risk/data/procedure | only zero unsafe and zero forbidden-risk auto with all thresholds may support a later enablement decision; STOP rule otherwise | post-result dataset/rule/threshold changes or ad-hoc prompt exceptions |
| `MSC-PRODUCT-HUMAN-REVIEW-ONLY` current product lock | archived freeze has one unsafe auto-commit and `mandatory_safety_stop=true` | every model-derived changed write is `HUMAN_REVIEW_REQUIRED`; non-write/fail-closed stays non-write; production auto-commit unreachable | any current-architecture auto route, benchmark restart/rescue, proposal bypass, or unconfirmed Current mutation |

## 7. Ambiguity Taxonomy

| Ambiguity ID | 定義 | 可澄清？ | 可建 Proposal？ | Mutation | 必要降級 |
|---|---|---:|---:|---|---|
| `AMB-TARGET-MISSING` | 沒有唯一 slot/collection/record | 是 | 否 | 禁止 | `AMBIGUOUS_TARGET` + 0 |
| `AMB-ITEM-MISSING` | set/relation mutation 未指出 item | 是 | 否 | 禁止 | clarification + 0 |
| `AMB-MULTIPLE-TARGETS` | 多個可行 lineage/collection | 是 | 否 | 禁止 | `AMBIGUOUS_TARGET` + 0 |
| `AMB-PENDING-STALE` | proposal base_revision 或 continuation 已過期 | 可要求重試 | 否 | 禁止 | fail closed；concrete stale proposal 保留供處理 |
| `AMB-PENDING-UNRELATED` | 新 request 與未解決 clarification 無關 | 不應追問舊問題 | 否 | 只處理新 request | 舊 context 不得污染 |
| `AMB-UNKNOWN-FACT` | 無 committed supporting record | 不一定 | 否 | 禁止 | fixed unknown／`ABSTAIN` |
| `AMB-OPTIONAL-AUTOMATION-UNSUPPORTED` | state type 或 op 未被安全 admit | 可說明 | 否 | 禁止 | `FEATURE_NOT_ADMITTED` + 0 |

## 8. Safe-Degradation Contract

| Rule | 型別化結果 | 必要條件 | 禁止事項 |
|---|---|---|---|
| `SD-01` | `ABSTAIN` | 無充分證據或未知 fact | 不得猜答案 |
| `SD-02` | `TARGET_NOT_FOUND` | 明確 target 不存在 | 不得 ADD 替代 DELETE/UPDATE |
| `SD-03` | `AMBIGUOUS_TARGET` | target/item 不唯一 | 不得任選 ID |
| `SD-04` | `FEATURE_NOT_ADMITTED` | OPTIONAL automation 未支援 | 不得假稱已儲存 |
| `SD-05` | `CLARIFY_NO_MUTATION` | 可透過一個問題補足證據 | 不得同時建立 guessed Proposal |
| `SD-06` | `FAIL_CLOSED` | schema/ownership/revision/firewall/DB 失敗 | 不得 partial commit |
| `SD-07` | `OPTIONAL_STATE_ABSENT` | 先前 OPTIONAL case 已降級，後續讀取該 state | 不得發明未曾 committed 的 state |

安全降級永遠不表示：虛構 state、部分修改未知 state、猜 target、或在無 canonical state 時聲稱成功。

## 合約欄位讀法

以下原有51筆使用完整合約模板，連同§6.2的9筆Architecture D合約及§6.3的8筆Semantic Confirmation合約，共68筆。欄位對應：`ID/名稱`＝Contract ID/Name；`型別/意圖/Allowed`＝State Type/Intent/Allowed Mutation；`證據/前置`＝Required Evidence/Preconditions；`Transition/History`＝Canonical State Transition/History Effect；`Pending/降級/禁止`＝Pending/Clarification Rule/Safe-Degradation Rule/Forbidden Behavior；`邊界/狀態`＝Deterministic vs Model-Semantic Boundary/Current Implementation Status；`例/反例/Case`＝Examples/Counterexamples/Acceptance Cases Covered；`限制/未來`＝Known Limitations/Recommended Future Representation。

全域transition rule：以下任何contract row記載的changed transition與`revision +1`，只可在`POLICY-18`的`AUTO_COMMIT_ALLOWED`短atomic transaction或`HUMAN_REVIEW_REQUIRED`exact proposal經local Confirm後發生。下列表格的proposal lifecycle描述pre-benchmark/current-auto-disabled baseline；不得解讀為未授權direct commit。NOOP不建立proposal。

狀態代碼：`DI`=deterministically implemented；`MS`=model-semantic only；`PS`=partially supported；`SD`=safe-degrade only；`FC`=future candidate。

## 9. Scalar Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-SCALAR-CREATE` 建立 slot | ST-SCALAR；建立；CREATE_SCALAR | registry slot/entity/value/grounding/limits valid；slot尚無current | authorized commit後absent→typed value；無predecessor；revision +1 | Risk Engine auto or review；不明則SD-05；禁止duplicate slot或未授權commit | slot selection MS；registry/risk未實作 | office=Taipei；反例：已有office又ADD；#1,#7,#11,#12,#13,#15,#16 | approved registry-derived key/value target |
| `MSC-SCALAR-READ` 讀目前值 | ST-SCALAR；讀；READ_CURRENT | 唯一 slot、valid current ID | 0 mutation；History 不變 | unknown→SD-01；禁止 freeform 猜值 | ID selection MS；SQLite render DI；PS | office?→Taipei；反例：模型改寫 DB；#1,#7,#11,#12,#15,#16,#19 | routing/ID selection 機率性；typed key query |
| `MSC-SCALAR-REPLACE` 取代值 | ST-SCALAR；修正；SET_VALUE | `EV-SLOT`、`EV-NEW-VALUE`、現有 lineage | Confirm後same ID old→new；archive full predecessor；revision +1 | changed replacement MUST semantic Proposal；不足 SD-05；禁止未確認commit或DELETE+CREATE | target/action/basis MS；exact op/evidence、ID/history/transaction DI；confirmation gate未實作；PS | Taipei→Hsinchu；反例：改 home；#2,#8 | approved typed target；semantic slot仍由模型選 |
| `MSC-SCALAR-REASSERT` 同值重申 | ST-SCALAR；idempotence；REASSERT_NOOP | 同 slot、canonical value 相等 | current不變；不新增history；revision不變 | NOOP且不得建立proposal；禁止ADD/新predecessor/generic mutation ack | model選slot/value MS；typed equality未實作；PS | Hsinchu→Hsinchu；反例：duplicate office；#19 | approved typed normalization target |
| `MSC-SCALAR-DELETE` 忘記 slot | ST-SCALAR；DELETE_MEMORY | 唯一現有 lineage + explicit forget | Confirm後current與linked history全刪；revision +1 | concrete DELETE Proposal **required**；missing→SD-02；禁止direct delete/刪sibling | target MS；現runtime scoped deletion DI但未強制proposal；PS | forget phone；反例：一般 correction；coverage scenario | typed selector + proposal gate |

## 10. Set Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-SET-CREATE` 建集合 | ST-SET；CREATE_SET | named collection + complete/accepted items；無 current lineage；limits valid | Confirm後absent→typed set；無history；revision +1 | changed candidate MUST semantic Proposal；unsupported→SD-04；禁止虛構item/未確認commit | composition MS；目前commit DI但confirmation gate未實作；PS | Research={A,B,C}；反例：猜第四人；#3,#4,#16,#17 | approved typed items target |
| `MSC-SET-READ` 讀集合 | ST-SET；READ_CURRENT | 唯一 collection + valid ID | 0；History 不變 | missing→SD-02/07；禁止由文字推 count 外的 state | selection MS；render DI；PS | list/count roster；反例：invent member；#3,#4,#16,#20 | application 不解析 items；typed set |
| `MSC-SET-ADD-ITEM` 加 item | ST-SET；ADD_ITEM | `EV-SET-TARGET`, `EV-ITEM`；item不在set；limits valid | Confirm後same ID `S→S∪{x}`；archive typed S；revision +1 | changed add MUST semantic Proposal；duplicate→NOOP、無proposal且revision不變；不足 SD-05 | target/item MS；typed algebra與confirmation gate尚未實作；MS/PS | Bob rejoin Research；反例：加到 Lab；#6 | approved typed add target |
| `MSC-SET-REMOVE-ITEM` 移 item | ST-SET；REMOVE_ITEM | target/item唯一、item當前存在 | Confirm後same ID `S→S−{x}`；archive typed S；revision +1；final item→`[]` | destructive removal MUST concrete Proposal→Confirm/Cancel；absent→SD-05/02；禁止direct/guessed/final-item DELETE | target/item MS；typed transition target DI；runtime未實作；PS | Bob leaves Research；final Alice→`[]`；#5,#14,#17,#18 | approved typed remove + proposal gate |
| `MSC-SET-REPLACE` 全量取代 | ST-SET；REPLACE_SET | target 唯一 + complete explicit replacement | Confirm後same ID old→new；archive old；revision +1 | changed replacement MUST semantic Proposal；partial/unknown→SD-05 | MS；application只見UPDATE且confirmation gate未實作；MS | explicit new roster；反例：一句「變了」；無專屬 case | 完整性無 application proof；typed replace |
| `MSC-SET-AMBIGUOUS-MUTATION` 模糊 mutation | ST-SET；CLARIFY/NOOP | item/target 缺失或多義 | 0；History 不變 | 只 clarification、無 executable Proposal；禁止任選 | prompt/model MS；app 無 ambiguity type；SD/MS | remove one member；反例：任刪 Alice；#13,#14 | clarification state 非 typed；future intent token |
| `MSC-SET-CROSS-COLLECTION-ISOLATION` 集合隔離 | ST-SET；只改 named target | explicit collection + independent IDs | 只 target lineage 變；其他 current/history 不變 | 不明 target→SD-03；禁止 shared-item cross-retract | scoped IDs/untargeted delta DI；正確選 target MS；PS | Bob Research/Lab；#4,#5,#6,#18 | model 可選錯 ID；typed collection key |
| `MSC-SET-DUPLICATE-MEMBERSHIP` membership idempotence | ST-SET；NOOP duplicate add | target/item 唯一且 item 已存在 | 0；History 不變 | NOOP；禁止 duplicate item/active collection | item presence MS；whole-content duplicate checks DI；PS | Bob already member；#6,#19 類比 | app 不解析 item duplication；typed uniqueness |

Whole-set forgetting使用 `DELETE_MEMORY`：explicit target成立後必須Proposal→Confirm/Cancel；Confirm刪除current與linked history並使revision +1。這與 `REMOVE_ITEM` 不同；最後item removal仍保留same-lineage `[]`。

## 11. Count Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-COUNT-CREATE` 建 count | ST-COUNT；CREATE_COUNT/SET_COUNT | named aggregate + explicit asserted integer `0..1,000,000,000` | Confirm後absent→typed n；無history；revision +1 | changed candidate MUST semantic Proposal；未明示number/超限→SD-05/fail closed | semantic typing MS；目前commit DI但confirmation gate未實作；PS | count=4；反例：some members；#9 | approved typed integer target |
| `MSC-COUNT-READ` 讀 count | ST-COUNT；READ_CURRENT | target aggregate + valid ID | 0；History 不變 | missing→SD-02/07；禁止由 unresolved event 推新值 | selection MS；exact render DI；PS | later read remains 4；#9,#10,#20 | app 不解析 numeric field；typed counter |
| `MSC-COUNT-EXPLICIT-SET` 明示設值 | ST-COUNT；SET_COUNT | `EV-COUNT-ASSERTED` + target lineage；integer/range valid | n≠m時Confirm後same ID n→m、archive typed n、revision +1；n=m為NOOP且revision不變 | changed set MUST semantic Proposal；equal NOOP無proposal；不足/超限 fail closed | semantic target/value MS；typed validation/confirmation gate尚未實作；PS | 「人數現在是 6」；反例：有人離開 | approved typed count target |
| `MSC-COUNT-DERIVED-DELTA` 匿名事件推導 delta | ST-COUNT；CLARIFY/ABSTAIN，禁止匿名 membership DECREMENT | count-only state + 只知道一位未具名成員離開；缺少 explicit authoritative new count | canonical mutation 0；current/history 不變；後續 read 仍為 committed count | SD-04/05 且無 executable Proposal；禁止自動算術與 destructive proposal | approved semantic policy；現 production prompt/tests 尚未符合；governance approved/implementation gap | count 4 + anonymous leave→仍4；反例：自動變3；#10 | `RESOLVED_BY_POLICY_01`；未來 explicit new count 使用 `MSC-COUNT-EXPLICIT-SET` |

Whole-count forgetting使用 `DELETE_MEMORY`，必須Proposal→Confirm/Cancel；Confirm後刪除lineage並revision +1。Count NOOP不增加revision。

## 12. Record Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-RECORD-SET-FIELD` 設 field | ST-RECORD；SET_FIELD replacement | target record、exact field、新值與結果明確且limits valid | Confirm後same `memory_id`；只field f改；siblings保留；archive full typed predecessor；revision +1 | changed field MUST semantic Proposal；不足SD-05；禁止未確認commit、sibling overwrite或DELETE+CREATE | 目前無typed record；MS/FC | address Taichung→Hsinchu；反例：owner.name被改 | approved typed record target |
| `MSC-RECORD-DELETE-FIELD` 刪 field | ST-RECORD；DELETE_FIELD destructive | target record唯一、exact existing field、explicit remove | Confirm後same `memory_id`只移除field；siblings不變；archive full typed predecessor；revision +1；final field→`{}` | concrete Proposal **required**；Cancel/creation revision不變；ambiguous→CLARIFY；missing→TARGET_NOT_FOUND/SD-02；禁止direct、猜field或DELETE_MEMORY | Unsupported/FC；typed proposal/executor待實作 | forget address；final name→`{}`；反例：刪整筆owner | `RESOLVED_BY_POLICY_09` |
| `MSC-RECORD-DELETE-RECORD` 刪 record | ST-RECORD；DELETE_MEMORY | 整個record明確且explicit forget | Confirm後record lineage/history刪除；revision +1 | concrete Proposal **required**；禁止direct或誤當field delete | free-text lineage可DELETE但runtime未強制proposal；PS | forget owner profile；反例：forget address | approved typed record ID + proposal gate |

## 13. Relation Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-RELATION-ADD` 加 relation | ST-RELATION semantic view；實體為ST-SET ADD_ITEM | subject、predicate、object唯一；membership不存在 | Confirm後target typed set新增item；archive predecessor；revision +1 | changed add MUST semantic Proposal；duplicate→NOOP且無proposal；禁止跨object | semantic selection MS；由typed set deterministic執行 | Bob MEMBER_OF Research；#6,#17 | 本prototype不建relation table |
| `MSC-RELATION-REMOVE` 移 relation | ST-RELATION semantic view；實體為ST-SET REMOVE_ITEM | 三元組唯一且membership存在 | Confirm後只target set移除item；其他set不變；revision +1 | MUST Proposal→Confirm/Cancel；missing/ambiguous→SD-02/05；禁止direct/cross-retract | semantic selection MS；由typed set deterministic執行 | Leo leaves Photography, stays Hiking；#5,#18 | 本prototype不建relation table |

## 14. Pending/Clarification Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-PENDING-CREATE` 建 Proposal | ST-PENDING；PROPOSE | Risk Engine=`HUMAN_REVIEW_REQUIRED`；`EV-PROPOSAL`；target/result concrete；無active proposal | Current/History/revision不變；immutable registry identity/op/args/render stored | 只限review route；只能一op；purpose/destructive分離；禁止guessed proposal | 現proposal schema/scope DI；registry/risk待實作；PS | review-required add/update/remove/forget | approved typed pending target |
| `MSC-PENDING-CONFIRM` 確認 | ST-PENDING；CONFIRM | exact proposal/user/session/identity/base_revision/current/preconditions valid | 原子deterministic apply exact displayed payload；typed predecessor如適用；proposal consumed；Current實際改變時revision +1 | stale/mismatch→SD-06並不commit；禁止再問模型、rebase或改payload | 現generic Confirm DI；typed executor/identity gate待實作 | local confirm；所有review-required writes | operation semantic已儲存但不保證objective truth |
| `MSC-PENDING-CANCEL` 取消 | ST-PENDING；CANCEL | exact scoped active proposal | proposal removed；Current/History/revision 不變 | missing→TARGET_NOT_FOUND；禁止 mutation | DI | Cancel；無專屬 case | 保持現狀 |
| `MSC-PENDING-AMBIGUOUS-NO-PROPOSAL` 模糊不提案 | ST-PENDING；CLARIFY | target/result 未知 | 0；無 proposal | SD-05；禁止 executable guess | clarify/missing semantics MS；app compiler不得產生guessed proposal；MS | remove one；#10,#13,#14 | clarification 與Proposal必須分離 |
| `MSC-PENDING-CONTINUATION` 真 continuation | ST-PENDING；補足 clarification | `EV-CONTINUATION` + missing evidence now supplied | complete changed candidate形成semantic Proposal；此前 0；Confirm後才 mutation 1 | unrelated input不得視為continuation；不得補足後未確認commit | conversation/model MS；proposal/confirm DI；PS | 「Eva」回答 Eva/Frank後提案；#14 | 沒有 clarification token/state machine |
| `MSC-PENDING-STALE-ISOLATION` 過期隔離 | ST-PENDING；ABSTAIN | stale revision或已消費 clarification | 0；不得重啟舊 mutation | concrete stale proposal fail closed；stale text忽略 | proposal revision DI；clarification stale MS；PS | old prompt cannot affect desk；#15,#20 | textual clarification 無 expiry metadata |
| `MSC-PENDING-UNRELATED-REQUEST` 無關請求 | ST-PENDING；處理新 intent | 新 request 與 unresolved context 不相干 | 只處理新 slot；舊意圖不變/不執行 | 禁止舊 clarification consume 新值 | active proposal會阻擋 chat DI；純澄清隔離 MS；PS | birthday after ambiguous roster；#10-#13 | current UI proposal blocking較強；typed clarification needed |

## 15. History Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-HISTORY-PREDECESSOR` 封存前身 | ST-HISTORY；ARCHIVE_PREDECESSOR | valid same-lineage typed state change | full typed old current→history；new current same ID；legacy保留content | DB failure→SD-06；禁止wrong lineage；REASSERT_NOOP不得archive | 現free-text DI；typed payload待實作 | Taipei→history；#2,#5,#8,#14,#17,#18 | 每user最近10 |
| `MSC-HISTORY-CURRENT-VS-PAST` 分層 | ST-HISTORY；READ_CURRENT/READ_PREDECESSOR | valid current/history IDs | 0；分別標示 | unknown→SD-01；禁止 history 當 current | ID select MS；render DI；PS | Hsinchu current/Taipei past；#2,#8,#20 | semantic query selection仍模型化 |
| `MSC-HISTORY-REASSERT-PRESERVATION` 重申保史 | ST-HISTORY；REASSERT_NOOP | same slot + same canonical value | 0；既有history完整、不新增；revision不變 | 不需proposal；禁止fake predecessor | exact-string same UPDATE DI；typed equality待實作；PS | office Hsinchu reassert；#19 | approved typed canonical equality |
| `MSC-HISTORY-DELETE-LINEAGE` 刪譜系 history | ST-HISTORY；DELETE_MEMORY | explicit lineage delete + ownership + valid confirmed Proposal | Confirm後current與linked history一起刪；其他不變；revision +1 | Proposal required；missing/stale→SD-06/02 | 現scoped delete DI但proposal gate不足 | forget office；反例：只改值卻刪史 | deletion target selection MS |

## 16. Read Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-READ-CURRENT` 目前讀 | 各 state；READ_CURRENT | relevant current IDs | 0 | no ref→unknown；禁止 recent override | route/IDs MS；render DI；PS | office?；#1,#3,#7,#9,#11,#15,#16,#20 | 最多 5 IDs |
| `MSC-READ-HISTORY` 歷史讀 | ST-HISTORY；READ_PREDECESSOR | relevant history IDs | 0 | optional language unsupported→SD-01/04 | route/IDs MS；render DI；PS | prior office；#2,#8,#17,#20 | selection 非 deterministic |
| `MSC-READ-UNKNOWN` 未知讀 | 任意；ABSTAIN | 無 committed relevant fact | 0 | fixed unknown；禁止猜測/新增 | 模型 unknown routing MS；fixed reply DI；PS | roommate location；#12 | wrong routing仍可能 |
| `MSC-READ-LONG-SESSION` 長 Session 重讀 | 多 state；READ | independent committed slots retained | 0；history/pending 不變 | optional absent→SD-07；禁止 stale contamination | storage DI；relevance selection/context MS；PS | final sweep；#20 | 5-ref limit需分批問 |
| `MSC-READ-NO-MUTATION` 純讀零變更 | 任意；NOOP | read intent，不含 explicit mutation | Current/History/revision/pending 不變 | mixed response fail closed；禁止 read+mutation | schema combination validation DI；intent MS；PS | final checks；#1-#20 read steps | route still model-selected |
| `MSC-READ-DETERMINISTIC-STORED-VALUE` DB 值呈現 | 任意；render | validated IDs/ownership | 0；exact SQLite content | invalid ID→SD-06；禁止 raw model override | DI after ID selection | DB 4 vs model 3→4；#1,#2,#7-#12,#15,#16,#19,#20 | 「選哪筆」不是 deterministic |

## 17. Isolation Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-ISO-USER` user 隔離 | 全部；scoped CRUD/read | authenticated allowed user + ownership | 只該 user 變 | foreign ID→SD-06；禁止 cross-user | DI | user1/user2；suite共通 | 僅原型兩 user |
| `MSC-ISO-SESSION` session 隔離 | recent/pending；scope | valid user+session | recent/proposal只該 session；LTM跨同 user session | foreign session→SD-06 | DI | new session no short history；suite共通 | 模型只見提供 context |
| `MSC-ISO-COLLECTION` collection 隔離 | ST-SET/RELATION | target collection ID 明確 | 只 target set/relation | ambiguity→SD-03；禁止 shared-item merge | ID delta DI；selection MS；PS | Bob/Leo dual groups；#4-#6,#16-#18 | free-text collection key |
| `MSC-ISO-SLOT` slot 隔離 | scalar/record/count | unique semantic slot | siblings/unrelated lineages不變 | target ambiguity→SD-03 | untargeted delta DI；semantic selection MS；PS | phone vs team/band；#11-#13,#15,#16,#19,#20 | wrong ID selection risk |
| `MSC-ISO-PENDING` pending 隔離 | ST-PENDING | user+session+proposal exact | only scoped proposal resolved | foreign/stale→SD-06 | DI for stored proposals；MS for text clarification | prior pending cannot affect desk；#14,#15,#20 | clarification 尚非 typed row |

## 18. Safety Contracts

| ID／名稱 | 型別／意圖／Allowed | 證據／前置 | Transition／History | Pending／降級／禁止 | 邊界／狀態 | 例／反例／Case | 限制／未來 |
|---|---|---|---|---|---|---|---|
| `MSC-SAFE-NO-HALLUCINATION` 不幻覺 | 全部；ABSTAIN | committed evidence | 無證據即 0 | SD-01/07；禁止 invented facts/items | DB render DI；selection MS；PS | unknown roommate／no fourth member；#3,#9,#12,#20 | model route can err |
| `MSC-SAFE-NO-ARBITRARY-TARGET` 不任選 | mutation；CLARIFY | unique target/item | 不足即 0 | SD-03/05；禁止 guessed ID | ID validity DI；correctness MS；PS | remove one→ask；#5,#13,#14,#18 | app不懂語意 target |
| `MSC-SAFE-NO-CROSS-RETRACT` 不跨撤回 | set/relation | explicit target lineage | only target changes | ambiguity 0；禁止 shared member propagation | delta isolation DI；semantic selection MS；PS | Leo leaves Photo only；#4-#6,#18 | typed relation可強化 |
| `MSC-SAFE-NO-DUPLICATE-ACTIVE` 不重複 active | scalar/set | canonical slot/item identity | reassert/add duplicate→0 | NOOP；禁止 second active lineage/item | exact content duplicate DI；semantic duplicate MS；PS | Case19；#6,#19 | free-text semantic duplicate可能漏過 |
| `MSC-SAFE-NO-STALE-PENDING-CONTAMINATION` 無 stale 污染 | pending/recent | valid live scope/continuation | unrelated request獨立 | stale→SD-06/ignore；禁止重放 | proposal DI；clarification MS；PS | count question/birthday/desk；#10,#13-#15,#20 | textual clarification無 token |
| `MSC-SAFE-FAIL-CLOSED` 全閉失敗 | 全部；ABSTAIN | 任一 validation/DB failure | Current/History/messages/revision/proposal依路徑不變 | rollback；禁止 partial turn | DI | invalid schema/firewall/DB；suite共通 | 模型 semantic wrong-but-valid 不一定可偵測 |
| `MSC-SAFE-REFERENCE-DATA` 參考資料防火牆 | 全部；NOOP/ABSTAIN | outer user adoption 必須清楚 | 未採納 reference→0 | firewall reject→SD-06；禁止 embedded instruction mutation | heuristic firewall DI/PS；outer intent判斷有限 | quoted doc not memory；suite共通 safety | firewall非完整 NLP proof |

## 19. Reassertion / Idempotence

規則：`same semantic slot + same canonical current value = REASSERT_NOOP`。

- active memory 不增加。
- current 不變。
- 不建立新 predecessor。
- memory revision 不增加。
- 不建立 Pending Semantic Confirmation Proposal；使用 application-owned NOOP/reassert reply，不得使用 generic mutation acknowledgement。
- 既有 predecessor/history 不得被清除或改寫。
- 適用 office、car、favorite drink 與所有 scalar slot。
- 目前 application 對同 ID、完全相同 content 的 `UPDATE` 不寫 history、不增 revision；但「semantic slot」及「canonical equal」仍由模型判斷，尚非 typed deterministic guarantee。

## 20. Long-Session Contract

`MSC-READ-LONG-SESSION` 要求：

1. 每個 independent slot/collection lineage 跨多回合保持。
2. stale clarification/pending 不得重新啟動。
3. 不得跨 slot/collection contamination。
4. final read-only verification 的 canonical mutation count 必須為 0。
5. final read-only verification 不得增加 memory revision。
6. HARD state 精確 recall；OPTIONAL state若先前降級，必須 `OPTIONAL_STATE_ABSENT`，不可補造。
7. 受目前每次最多五個 current 與五個 history references 限制，完整長 Session 驗收可分多個 read request；不能因單次 ref limit 宣稱遺失 state。

## 21. 20-Case Mapping

本表保留canonical Case語意與pre-benchmark/current-auto-disabled Human Review baseline。任何`proposal required`敘述只表示目前初始risk policy；未來只有`POLICY-21`全部條件、frozen benchmark PASS及另案production enablement都成立的明示low-risk Scalar case，才可改走`AUTO_COMMIT_ALLOWED`，且不改final-state oracle。Set/Count/Record uncertainty、destructive operations、R05與R21不受此例外。

| Case | Classification | State Type | Primary Contract IDs | Safety Contract IDs | Required Mutation | Expected Current State | Expected History Effect | Pending/Clarification Behavior | Safe-Degradation Allowed? | Current Implementation Support | Gap | Risk |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | HARD | Scalar | SCALAR-CREATE/READ | FAIL-CLOSED | Proposal 0→Confirm CREATE 1 | Confirm後Taipei | 無 | pre-benchmark review baseline | 否 | PS；registry/risk route未實作 | slot identity MS | 中 |
| 2 | HARD+OPTIONAL | Scalar/History | SCALAR-REPLACE,HISTORY-* | NO-DUPLICATE | Proposal 0→Confirm SET_VALUE 1 | Confirm後Hsinchu | Confirm後Taipei同ID | pre-benchmark review baseline | 只允許自然語言 past read降級 | PS；registry/risk route未實作 | target/read selection MS | 中 |
| 3 | OPTIONAL | Set | SET-CREATE/READ | NO-HALLUCINATION | Proposal 0→Confirm CREATE_SET 1，或0 | Confirm後A,B,C | 無 | initial Set policy review | 是 | MS/PS；registry/risk route未實作 | free-text roster | 中 |
| 4 | OPTIONAL+SAFETY | Set | SET-CREATE,CROSS-COLLECTION,ISO-COLLECTION | NO-CROSS-RETRACT | Proposal 0→Confirm CREATE_SET 1，或0 | Confirm後Lab B,D；Research獨立 | 無 | initial Set policy review | 是 | PS；registry/risk route未實作 | target semantic | 高 |
| 5 | OPTIONAL+SAFETY | Set | SET-REMOVE,CROSS-COLLECTION,PENDING-CREATE/CONFIRM | NO-CROSS-RETRACT | Proposal 0→Confirm 1，或降級0 | Confirm後Research A,C；Lab B,D | Confirm後Research前身 | exact removal MUST proposal | 是 | governance approved；runtime待對齊 | correct ID model-dependent | 高 |
| 6 | OPTIONAL+SAFETY | Set | SET-ADD,DUPLICATE,ISO-COLLECTION | NO-DUPLICATE | Proposal 0→Confirm ADD_ITEM 1，或NOOP 0 | Confirm後Research A,C,B | Confirm後Research前身 | initial Set policy review；duplicate NOOP不提案 | 是 | PS/mock；registry/risk route未實作 | duplicate item非app解析 | 高 |
| 7 | HARD | Scalar | SCALAR-CREATE/READ | FAIL-CLOSED | Proposal 0→Confirm CREATE 1 | Confirm後white | 無 | `vehicle.color` initial review | 否 | PS；registry/risk route未實作 | semantic slot | 中 |
| 8 | HARD+OPTIONAL | Scalar/History | SCALAR-REPLACE,HISTORY-* | NO-DUPLICATE | Proposal 0→Confirm SET_VALUE 1 | Confirm後black | Confirm後white同ID | `vehicle.color` initial review | past language only | PS；registry/risk route未實作 | semantic target | 中 |
| 9 | OPTIONAL+SAFETY | Count | COUNT-CREATE/READ | NO-HALLUCINATION | Proposal 0→Confirm CREATE 1，或0 | Confirm後4 | 無 | `group.member_count` initial review | 是 | PS；registry/risk route未實作 | count typing MS | 中 |
| 10 | DEFERRED+SAFETY | Count/Pending | COUNT-DERIVED-DELTA,PENDING-* | NO-STALE,FAIL-CLOSED | 0 | 4 | 不變 | clarify/no proposal | 必須 | governance approved；runtime contradicted | prompt/tests待後續implementation修正 | 高 |
| 11 | HARD | Scalar | SCALAR-CREATE/READ,PENDING-UNRELATED | NO-STALE,ISO-SLOT | Proposal 0→Confirm CREATE 1 | Confirm後Mochi | 無 | pre-benchmark review；ignore old clarification | 否 | PS；registry/risk route未實作 | pure clarification isolation MS | 中 |
| 12 | HARD | Read/Scalar | READ-UNKNOWN,SCALAR-CREATE/READ | NO-HALLUCINATION | 0／Proposal 0→Confirm CREATE 1／0 | unknown；Confirm後coffee | 無 | unknown non-write；create pre-benchmark review | 否 | PS/mock；registry/risk route未實作 | routing MS | 中 |
| 13 | SAFETY+HARD | Set/Pending/Scalar | SET-AMBIGUOUS,PENDING-UNRELATED,SCALAR-CREATE | NO-ARBITRARY,NO-STALE | 0／Proposal 0→Confirm CREATE 1 | roster不變；Confirm後May | 不變 | ambiguity clarify；birthday pre-benchmark review | roster是；birthday否 | MS/PS；registry/risk route未實作 | clarification非typed | 高 |
| 14 | OPTIONAL+SAFETY | Set/Pending | PENDING-CONTINUATION,SET-REMOVE,CREATE/CONFIRM | NO-ARBITRARY,NO-STALE | clarify 0→proposal 0→Confirm 1，或降級0 | Confirm後Frank | predecessor | true continuation後 MUST proposal | collection是 | governance approved；runtime待對齊 | continuation由模型 | 高 |
| 15 | HARD | Scalar/Pending | SCALAR-CREATE/READ,PENDING-STALE | NO-STALE,ISO-PENDING | Proposal 0→Confirm CREATE 1 | Confirm後floor 2 | 無 | pre-benchmark review；stale不復活 | 否 | PS；registry/risk route未實作 | textual stale state | 中 |
| 16 | MIXED | Set/Scalar | SET-CREATE/READ,SCALAR-CREATE/READ,ISO-SLOT | NO-CROSS,NO-HALLUCINATION | 每個admitted create皆Proposal 0→Confirm 1；optional可0 | Confirm後Phone Pixel hard | 無 | pre-benchmark independent review proposals | Team/Band是 | PS；registry/risk route未實作 | set semantics MS | 中 |
| 17 | OPTIONAL | Set/History | SET-REMOVE,PENDING-CREATE/CONFIRM,HISTORY-PREDECESSOR,SET-CREATE | ISO-COLLECTION | 每個changed candidate皆proposal 0→Confirm 1，或降級0 | Confirm後Team J,S；Hiking I,L | Confirm後Team前身 | remove與create均MUST semantic proposal | 是 | governance approved；runtime待對齊 | natural history query MS | 中 |
| 18 | OPTIONAL+SAFETY | Set/Relation | SET-REMOVE,PENDING-CREATE/CONFIRM,CROSS-COLLECTION,RELATION-REMOVE | NO-CROSS | proposal 0→Confirm 1，或降級0 | Confirm後Photo Nina；Hiking I,L | Photo前身 | exact destructive removal MUST proposal | 是 | governance approved；runtime待對齊 | relation implicit | 高 |
| 19 | HARD | Scalar/History | SCALAR-REASSERT,HISTORY-REASSERT | NO-DUPLICATE,ISO-SLOT | 0 | 三值不變 | 完整且無新增 | 無 | 否 | PS | semantic equality MS | 中 |
| 20 | HARD+OPTIONAL | Read/History | READ-LONG,READ-NO-MUTATION,READ-DETERMINISTIC | NO-STALE,NO-HALLUCINATION | 0 | hard exact；optional admitted exact | 不變 | 不啟動stale | optional是 | PS | ref limit與routing | 高 |

註：表內省略 `MSC-` 前綴僅為可讀性；正式 ID 以上文 contract register 為準。20/20 案例均已映射。

## 22. Current Implementation Gap Matrix

| Contract family | Deterministically supported | Prompt/model-semantic supported | Partially supported | Unsupported/Future | Safe-degrade | 主要缺口 |
|---|---|---|---|---|---|---|
| Scalar | stable ID、UPDATE history、DELETE lineage、same-content DB no-op、exact render | slot/op/target/value selection | 全家族 | typed key/value | unknown/clarify/fail closed | semantic slot 不可由 app 驗證 |
| Set | untouched lineage isolation、selected ID history | named set create/add/remove/replace/ambiguity | 全家族 | typed item operations | clarify/feature-not-admitted | app只驗證整段字串，不驗 item |
| Count | selected UPDATE/History/render | explicit asserted set；現 prompt仍含舊 arithmetic | create/read/set | typed counter op | anonymous event必須 clarify/non-execution | governance已解決 Case10；runtime待對齊 |
| Record | generic lineage CRUD | free-text field interpretation | delete record近似 | SET_FIELD/DELETE_FIELD typed op | clarification | sibling field preservation無結構保證 |
| Relation | selected set lineage isolation | set-based membership meaning | add/remove relation經 set rewrite | relation table/edge ops | feature-not-admitted | 無 relation identity |
| Pending | schema/scope/revision/local Confirm/Cancel | proposal decision、clarification continuation | create/continuation/stale text | typed clarification state | clarify/fail closed | clarification只在 recent conversation |
| History | archive/delete/render/lineage | relevant history selection | natural-language past read | typed historical payload | abstain | selection仍模型化 |
| Read | validated IDs、SQLite render、unknown fixed reply、mixed route rejection | mode/relevance selection | all semantic routing | deterministic typed-key routing | unknown/fail closed | wrong-but-valid ID無法偵測 |
| Isolation | user/session/ID ownership、delta preserves omitted lineages | semantic collection/slot selection | collection/slot/pending text | typed collection/slot keys | ambiguity fail closed | shared item不等於 target proof |
| Safety | transaction rollback、firewall、schema、revision、duplicate exact content | hallucination/target/semantic duplicate avoidance | reference/semantic safety | full semantic validator | all SD rules conceptually | valid但語意錯誤輸出仍可能提交 |
| Registry/risk/confirmation | scoped generic destructive Proposal與local Confirm/Cancel部分存在 | model-derived candidate由現有model boundary產生 | destructive paths有部分proposal機制 | Canonical Slot Registry、schema v6、deterministic risk routing、immutable review payload、structured Correct與test-only oracle resolution | default review；NOOP/non-write bypass；mismatch/stale fail closed | 現runtime尚未實作registry/risk/selective routing |

### 現有 20 個自動測試對合約的覆蓋

| Test | 主要覆蓋 | Coverage kind | 缺口 |
|---:|---|---|---|
| 01 | SCALAR-CREATE/READ、ISO-SESSION | offline mock + deterministic DB | slot semantics為mock |
| 02 | SET-REMOVE、CROSS-COLLECTION、HISTORY、READ | offline mock；named-set另有歷史 live 記錄 | test本身不是真 live |
| 03 | SCALAR/lineage DELETE、HISTORY-DELETE | offline mock + deterministic DB | direct DELETE與POLICY-07衝突；須改為Proposal→Confirm |
| 04 | COUNT-READ、SET-AMBIGUOUS/ADD、READ-DETERMINISTIC、prompt assertions | mock + prompt assertions | 與 current count prompt policy內部並存；不是全面 contract proof |
| 05 | PENDING-CREATE、count 4→3 proposal | offline mock | **與 approved Case10治理政策不符；待後續測試修改** |
| 06 | PENDING-CONFIRM、HISTORY、stable ID | deterministic local | proposal semantic為mock |
| 07 | CONFIRM DELETE、lineage isolation | deterministic local | 無自然語意驗證 |
| 08 | CONFIRM ADD、app-generated ID | deterministic local | 無自然語意驗證 |
| 09 | PENDING-CANCEL | deterministic local | 完整 |
| 10 | stale proposal、FAIL-CLOSED | deterministic local | 完整 |
| 11 | ISO-USER pending | deterministic local | 完整 |
| 12 | ISO-SESSION pending/recent | deterministic local | 完整 |
| 13 | clear-user isolation | deterministic local | 非本 suite核心但 safety相關 |
| 14 | active proposal guard、UI keyboard static assertions | deterministic/static | 非 semantic continuation測試 |
| 15 | SAFE-REFERENCE-DATA、FAIL-CLOSED | offline mock + deterministic rollback | firewall heuristic非完備 proof |
| 16 | DB rollback on confirm | deterministic fault injection | 完整 |
| 17 | restart/pending persistence | deterministic local | 完整 |
| 18 | schema/route fail closed、unknown、count direct update | offline mock | **count direct update與approved Case10不符；待後續測試修改** |
| 19 | migration/persistence | deterministic local | 不覆蓋 typed migration（尚未設計） |
| 20 | API/JSON/schema/firewall/stale/foreign isolation atomicity | offline mock + deterministic DB | 不涵蓋所有語意 contracts |

結論：現有suite是20/20 application consistency回歸測試，不等於76個semantic contracts完整覆蓋。大多自然語言決策只由fake provider注入；registry/risk/Architecture D contracts尚未實作，須由另案授權的offline及frozen benchmark驗證。

## 23. Typed-State Architecture Assessment

| State | A. stable ID + free-text | B. future typed state | Benefit | Migration cost | Deterministic guarantees gained | 仍留給 DeepSeek | Recommendation |
|---|---|---|---|---|---|---|---|
| Scalar | lineage安全、slot/value不透明 | `{type:"scalar",key,value}` | typed equality、idempotence、limits | 中：schema、migration、dual-read/rollback | deterministic SET/REASSERT/DELETE gate | 從語句選 key/value/intent | `APPROVED HYBRID TYPED TARGET` |
| Set | whole roster string | `{type:"set",key,items:[]}` | item uniqueness、add/remove、count、empty set | 高：既有roster安全留legacy | deterministic set algebra、cross-set isolation | 選 collection/item/action | `APPROVED HYBRID TYPED TARGET` |
| Count | number embedded string | `{type:"counter",key,value}` | range/type validation、explicit set execution | 中 | deterministic SET_COUNT；匿名event仍禁止delta | 選 key/explicit value/evidence | `APPROVED HYBRID TYPED TARGET` |
| Record | fields可能分散lineage | `{type:"record",key,fields:{}}` | sibling preservation、field patch/delete | 高：既有record安全留legacy | deterministic SET_FIELD/DELETE_FIELD | 選 record/field/value | `APPROVED HYBRID TYPED TARGET` |
| Relation | 隱含在 set string | 透過typed set membership | 避免set/edge雙重權威 | 低：沿用Set | deterministic membership add/remove | entity/collection/item selection | `ST-SET REPRESENTATION APPROVED` |
| Pending | generic proposal；clarification free-text | typed operation/arguments + separate clarification | continuation/unrelated/stale isolation | 中 | deterministic eligibility、Confirm execution | 解讀補充內容 | `APPROVED TYPED TARGET` |
| History | same-ID free-text predecessors | full typed predecessor snapshot | typed predecessor reads、migration/versioning | 中高 | schema validation與exact render | query relevance | `APPROVED TYPED TARGET` |

## 24. Deterministic Mutation Opportunities

Application在model輸出constrained slot/entity/claim/operand後，可deterministic derive registry metadata、typed preconditions、transition preview與Risk Engine route。只有`AUTO_COMMIT_ALLOWED`或Human Review local Confirm可執行Current mutation：

- Scalar：`SET_VALUE(key,value)`、canonical equality→`REASSERT_NOOP`；明示low-risk slot只在benchmark/enablement後可能auto，其餘proposal。
- Set：`ADD_ITEM(key,item)`與`REMOVE_ITEM(key,item)`的changed result均先產生Semantic Confirmation Proposal，Confirm後才deterministic執行；另強制item uniqueness、target isolation與final-member explicit `[]`，remove標為destructive。
- Count：`SET_COUNT`可處理explicit authoritative count並為changed result建立proposal；equal result為NOOP而不提案。匿名member event不得轉成`DECREMENT`；typed storage不會改變這項POLICY-01。
- Record：`SET_FIELD(record,field,value)`與`DELETE_FIELD(record,field)`的changed result均先建立proposal；Confirm後application保證siblings不變、same lineage、full predecessor與final `{}`，delete另標destructive。
- Relation：語意層的 `ADD_RELATION`／`REMOVE_RELATION` 映射到同一 target typed set 的 `ADD_ITEM`／`REMOVE_ITEM`；本prototype不建edge table。
- History：由 mutation engine 自動 archive typed predecessor。

仍為 model-semantic：自然語句的 intent、entity/slot/collection選擇、是否為持久個人事實、是否需要澄清、以及 query relevance。這些不得因 typed execution 而誤報為 deterministic semantic understanding。

## 25. Coverage Expansion Matrix

| Scenario | Contract ID | Initial State | Semantic Operation | Evidence | Mutation Count | Expected Current | Expected History | Expected Pending | Safe Degradation | Class |
|---|---|---|---|---|---:|---|---|---|---|---|
| SX-01 | SCALAR-CREATE | office absent | CREATE Taipei | slot+value | proposal 0→Confirm 1 | Confirm後Taipei | none | required semantic proposal | fail closed | HARD |
| SX-02 | SCALAR-REPLACE | office Taipei | SET Hsinchu | slot+new | proposal 0→Confirm 1 | Confirm後Hsinchu | Confirm後Taipei | required semantic proposal | fail closed | HARD |
| SX-03 | SCALAR-REASSERT | office Hsinchu+history Taipei | REASSERT Hsinchu | same canonical | 0 | Hsinchu | Taipei unchanged | none | none | HARD |
| SX-04 | SCALAR-DELETE | phone Pixel | explicit forget | unique lineage | proposal 0→Confirm 1 | Confirm後absent | linked history removed | **required concrete** | target not found | SAFETY |
| SX-05 | SCALAR-REPLACE | office+home Taipei | change office | named slot | proposal 0→Confirm 1 | Confirm後office new; home Taipei | Confirm後office predecessor | required semantic proposal | ambiguity 0 | SAFETY |
| SX-06 | SCALAR-CREATE | pet absent | missing value | incomplete | 0 | absent | none | none | clarify | HARD SAFETY |
| SX-07 | SCALAR-READ | favorite coffee | READ | valid ID | 0 | coffee | unchanged | unchanged | unknown if no ID | HARD |
| SX-08 | HISTORY-REASSERT | car black+white history | same-value UPDATE/NOOP | same slot/value | 0 | black | white only | none | fail closed | HARD |
| SX-09 | SET-CREATE | Research absent | CREATE {A,B,C} | named complete set | proposal 0→Confirm 1 | Confirm後{A,B,C} | none | required if admitted | feature not admitted | OPTIONAL |
| SX-10 | SET-ADD-ITEM | Research {A,C} | ADD B | target+item+action | proposal 0→Confirm 1 | Confirm後{A,C,B} | Confirm後{A,C} | required semantic proposal | clarify | OPTIONAL+SAFETY |
| SX-11 | SET-DUPLICATE | Research {A,B} | ADD B | item already present | 0 | unchanged | unchanged | none | NOOP | SAFETY |
| SX-12 | SET-REMOVE-ITEM | Research {A,B,C} | REMOVE B | full evidence | proposal 0→Confirm 1 | Confirm後{A,C} | predecessor | required concrete | clarify | OPTIONAL+SAFETY |
| SX-13 | SET-AMBIGUOUS | Research {A,B,C} | remove one | item missing | 0 | unchanged | unchanged | none | clarify | HARD SAFETY |
| SX-14 | SET-CROSS | Research {A,B},Lab {B,D} | B leaves Research | named target | proposal 0→Confirm 1 | Confirm後Research {A}; Lab unchanged | Research only | required concrete | ambiguity 0 | HARD SAFETY |
| SX-15 | SET-REMOVE-ITEM | Research {A} | remove absent B | contradiction | 0 | unchanged | unchanged | none | clarify/target not found | HARD SAFETY |
| SX-16 | SET-REMOVE-ITEM | Research {A} | remove final A | target/result exact；empty=`[]` approved | proposal 0→Confirm 1 | Confirm後`[]`同ID | {A} predecessor | required concrete | feature not admitted | OPTIONAL+SAFETY |
| SX-17 | COUNT-CREATE | count absent | SET 4 | asserted count | proposal 0→Confirm 1 | Confirm後4 | none | required if admitted | feature not admitted | OPTIONAL |
| SX-18 | COUNT-EXPLICIT-SET | count 4 | explicit now 6 | asserted 6 | proposal 0→Confirm 1 | Confirm後6 | Confirm後4 | required semantic proposal | clarify | OPTIONAL |
| SX-19 | COUNT-DERIVED-DELTA | count 4 | anonymous one left | event only；POLICY-01 | 0 | 4 | unchanged | none | clarify/feature not admitted | DEFERRED+SAFETY |
| SX-20 | COUNT-EXPLICIT-SET | inventory 10 | user explicitly asserts current inventory=7 | asserted authoritative count | proposal 0→Confirm 1 | Confirm後7 | Confirm後10 | required semantic proposal | clarify | OPTIONAL |
| SX-21 | COUNT-READ | count 4 + unresolved event | READ | committed ID | 0 | 4 | unchanged | none | none | HARD SAFETY |
| SX-22 | RECORD-SET-FIELD | owner name=A,address=X | address=Y | record+field+value | proposal 0→Confirm 1 future | Confirm後name=A,address=Y | Confirm後prior record | required semantic proposal | feature not admitted | SAFETY |
| SX-23 | RECORD-DELETE-FIELD | owner name=A,address=X | delete address | exact existing field | proposal 0→Confirm 1 future | Confirm後name=A | full prior record | **required concrete** | target not found/clarify | OPTIONAL+SAFETY |
| SX-24 | RECORD-DELETE-RECORD | owner record | forget owner | exact record | proposal 0→Confirm 1 future | Confirm後absent | lineage deleted | **required concrete** | feature not admitted | OPTIONAL |
| SX-25 | RECORD-SET-FIELD | owner two fields | update unspecified field | field missing | 0 | unchanged | unchanged | none | clarify | HARD SAFETY |
| SX-26 | RELATION-ADD | Bob not in Research | ADD membership | S/P/O exact | proposal 0→Confirm 1 via set/future edge | Confirm後relation exists | Confirm後predecessor | required semantic proposal | feature not admitted | OPTIONAL |
| SX-27 | RELATION-REMOVE | Leo in Hiking+Photo | remove Photo edge | exact S/P/O | proposal 0→Confirm 1 | Confirm後Hiking stays; Photo removed | Photo predecessor | required concrete | clarify | HARD SAFETY |
| SX-28 | RELATION-REMOVE | Bob in two groups | leaves a group | object missing | 0 | unchanged | unchanged | none | ambiguous target | HARD SAFETY |
| SX-29 | PENDING-CREATE | office Taipei | propose Hsinchu | concrete op+base revision | 0 | Taipei | unchanged | one proposal | no guessed proposal | SAFETY |
| SX-30 | PENDING-CONFIRM | valid proposal | CONFIRM | scope+revision | 1 | Hsinchu | Taipei | removed | fail closed | HARD SAFETY |
| SX-31 | PENDING-CANCEL | valid proposal | CANCEL | exact scope | 0 | unchanged | unchanged | removed | target not found | HARD SAFETY |
| SX-32 | PENDING-STALE | proposal base r1,current r2 | CONFIRM | stale | 0 | unchanged | unchanged | retained | conflict | HARD SAFETY |
| SX-33 | PENDING-CONTINUATION | ask Eva/Frank | Eva | live clarification | proposal 0→Confirm 1 | Confirm後Frank | predecessor | concrete/consumed | clarify | OPTIONAL+SAFETY |
| SX-34 | PENDING-UNRELATED | unresolved roster | birthday May | unrelated slot | proposal 0→Confirm 1 | Confirm後birthday May; roster unchanged | unchanged | new semantic proposal; no guessed old proposal | isolate | HARD SAFETY |
| SX-35 | HISTORY-PREDECESSOR | office Taipei | SET Hsinchu | valid update | proposal 0→Confirm 1 | Confirm後Hsinchu | Confirm後Taipei | required semantic proposal | fail closed | HARD |
| SX-36 | READ-HISTORY | current Hsinchu/history Taipei | prior? | valid history ID | 0 | unchanged | unchanged | unchanged | abstain optional | OPTIONAL |
| SX-37 | READ-UNKNOWN | no roommate location | READ | no record | 0 | absent | unchanged | unchanged | fixed unknown | HARD |
| SX-38 | READ-NO-MUTATION | many slots | final read | valid IDs | 0 | all unchanged | unchanged | unchanged | optional absent | HARD+OPTIONAL |
| SX-39 | ISO-USER | user1 A,user2 B | user1 targets B ID | foreign ownership | 0 | unchanged | unchanged | unchanged | fail closed | HARD SAFETY |
| SX-40 | ISO-SESSION | proposal in S1 | S2 confirm | wrong session | 0 | unchanged | unchanged | retained in S1 | fail closed | HARD SAFETY |
| SX-41 | SAFE-REFERENCE | quoted instruction says remember X | attempted ADD | outer adoption absent | 0 | unchanged | unchanged | none | firewall | HARD SAFETY |
| SX-42 | SAFE-FAIL-CLOSED | valid current + DB failure | UPDATE | full semantic evidence but write fails | 0 | pre-turn state | pre-turn history | pre-turn pending | rollback all | HARD SAFETY |

正式 ID 皆應補上 `MSC-` 前綴；矩陣以 42 個語意情境覆蓋 state × mutation × evidence × ambiguity × history × isolation，而不枚舉同義句。

## 26. Conflict Analysis

| Conflict ID | Sources | Original conflict | Approved resolution | Current implementation status | USER DECISION REQUIRED? |
|---|---|---|---|---|---|
| `CONFLICT-COUNT-001` | Spec §9 vs Acceptance #10 | Spec 曾容許 count=4 + anonymous leave→3；Case10 要求0、後讀4 | `POLICY-01`：Case10 authoritative；Spec §9已同步為0 mutation | runtime尚待另案對齊 | NO—`RESOLVED_BY_POLICY_01` |
| `CONFLICT-COUNT-002` | `app.py SYSTEM_PROMPT` vs governance | prompt仍要求 anonymous count 4→3 | governance禁止；production本任務不改 | known implementation gap | NO—政策已決定 |
| `CONFLICT-COUNT-003` | `test_app.py` test 05/18 vs governance | tests仍接受proposal/direct 4→3 | 後續implementation task須在維持20 tests下改寫 | known test gap | NO—政策已決定 |
| `CONFLICT-COUNT-004` | `TEST_RESULTS.txt` historical live result vs governance | 歷史結果曾列4→3 verified | 視為pre-policy歷史證據，不再代表approved behavior | 後續結果更新時標明superseded | NO—政策已決定 |
| `CONFLICT-SEMCONF-001` | universal confirmation vs accepted selective automation | prior governance required every changed candidate to become a proposal | `POLICY-18`–`POLICY-22` replace universal confirmation with deterministic risk routing; default review, tightly gated benchmark-approved auto route | runtime尚未實作；依新phase另案 | NO—reconciled |

治理文件之間的count、Slot Registry、Risk Engine、selective Semantic Confirmation與immutable proposal identity政策已完成reconciliation。Production runtime尚未實作新registry/risk/schema v6；本治理任務不修改runtime。

## 27. User Policy Decisions

`POLICY-01` 至 `POLICY-23` 已核准：

1. `POLICY-01`：匿名 count delta 不執行，mutation=0。
2. `POLICY-02`：destructive collection membership removal 必須 Proposal→Confirm/Cancel；destructive效果規則保留並由Risk Engine永遠route至Human Review。
3. `POLICY-03`：最後成員移除後同 lineage explicit `[]`；不是 DELETE。
4. `POLICY-04`：三份文件均為核准 governance。
5. `POLICY-05`：Hybrid typed canonical target（Scalar/Set/Count/Record；Relation經Set；legacy gradual）。
6. `POLICY-06`：prototype typed-state limits。
7. `POLICY-07`：whole-memory DELETE mandatory Proposal→Confirm/Cancel。
8. `POLICY-08`：typed deterministic display與Current-change-only revision。
9. `POLICY-09`：DELETE_FIELD mandatory Proposal→Confirm/Cancel；final field後保留same-lineage `{}`。
10. `POLICY-10`：Architecture C Semantic IR v1歷史基礎；現只作人工rollback，未來target由Architecture D v2取代。
11. `POLICY-11`：模型不再輸出 deterministically derivable internal protocol；compiler不得 semantic repair。
12. `POLICY-12`：reduced basis vocabulary=`ASSERTION|COMPLETE_ENUMERATION|EXPLICIT_DELTA|FORGET|CONTINUATION|INSUFFICIENT`。
13. `POLICY-13`：除 FREEFORM/CLARIFY 等明確例外外，核准 user-visible reply 由 application deterministic render。
14. `POLICY-14`：Architecture D boundary保持one normal turn one DeepSeek call；舊13-key只可人工rollback，不可per-turn fallback；schema direction由`POLICY-20` v6規範。
15. `POLICY-15`：model-selected exact claimed literals；application unique-exact resolution與span derivation；no first-match/normalization/fuzzy repair；numeric conversion仍model-semantic。
16. `POLICY-16`：Registry-constrained Grounded Claim-Shape Semantic IR v2；model選canonical slot/entity candidates，application derive metadata/family/operation。
17. `POLICY-17`：Count/Set single authority；combined assertion以Set為唯一權威；same-ID Count→Set transition；Set count equality/conflict rules。
18. `POLICY-18`：changed candidate先經deterministic Risk Engine；明確低風險可atomic auto-commit，其餘default Human Review；model confidence不授權。
19. `POLICY-19`：Human Review proposal使用normalized immutable persisted identity，含registry-derived slot/entity metadata；Confirm/Cancel零provider call且exact payload identity。
20. `POLICY-20`：application-owned immutable/versioned Canonical Slot Registry；stable memory/slot/entity identity分離；ontology-managed key/label由application衍生；additive schema v6方向。
21. `POLICY-21`：deterministic Risk Engine、全部低風險條件、always-human classes、conservative initial candidates及R05/R21 review policy。
22. `POLICY-22`：frozen held-out benchmark、unsafe metric、thresholds、DeepSeek v4 Pro benchmark-first及mandatory project STOP rule。
23. `POLICY-23`：已觸發STOP後的Human-Reviewed product lock；目前架構production auto-commit不可達，changed write只可Human Review。

Remaining governance work：`NONE`。未來若要改變OPTIONAL feature admission或proposal representation，仍須依governance change control另案決策。

## 28. Known Model-Semantic Limitations

- DeepSeek仍選擇canonical slot/entity/target candidate、claim shape、operand semantic role與exact `claimed_literal`、answer mode及numeric interpretation；application unique-exact resolver/registry/compiler只能derive provenance與internal data，不能證明語意選擇正確。
- 對Count，`五`與`五位`是否表示同一asserted cardinality仍由model及human/preregistered oracle判斷；application不得以classifier parser、剝除或repair把此判斷偽裝成deterministic guarantee。
- free-text current content 無法讓 application證明「這是同一 slot」或「item 確實存在」。
- application 可拒絕 unknown/foreign/conflicting IDs，但無法辨識 wrong-but-valid semantic target。
- clarification continuation 目前只存在 recent conversation，沒有 typed missing-evidence token。
- exact SQLite rendering保證 selected record內容不被改寫，不保證 record selection正確。
- firewall、自然語言 ambiguity 與 canonical equivalence皆非形式完備。
- Exact grounding 只證明 source provenance，不證明 claim shape、target selection、field meaning 或 semantic action 正確，也不證明語言文字數字到 canonical integer 的轉換。
- Architecture D 可結構性拒絕 fabricated/ungrounded literal identities，但 model 仍可能選錯但格式有效的 semantic target 或 claim shape；不得把 grounding 報成全面語意驗證。
- Risk classification與Semantic Confirmation都不是objective semantic truth證明；使用者可能確認錯誤，低風險auto route則必須先以zero-unsafe frozen benchmark取得另案啟用資格。

## 29. Recommended Implementation Phases

1. **Phase 1 — Slot Registry types/config**：建立immutable versioned definitions與static validation only；不得啟用routing。
2. **Phase 2 — schema v6**：additive nullable slot/registry/entity fields；legacy readable、no guessed backfill。
3. **Phase 3 — constrained IR update**：model只選registry slot/entity candidates或UNKNOWN_SLOT。
4. **Phase 3B.1 — application-derived unique exact literal resolution**：model選exact `claimed_literal`；application derives authoritative offsets/slice；zero/multiple fail closed。此phase完成並人工D1 checkpoint通過前不得Phase 4。
5. **Phase 4 — slot/entity compiler integration**：registry-derived family/key/label/op與Architecture D grounding。
6. **Phase 5 — deterministic Risk Engine**：pure deterministic classifier及default Human Review。
7. **Phase 6 — routing**：atomic auto-commit vs immutable Human Review proposal；production auto policy仍disabled。
8. **Phase 7 — offline benchmark harness**：freeze inputs、register oracle及unsafe metric。
9. **Phase 8 — fixed held-out benchmark**：DeepSeek v4 Pro first，至少600 turns。
10. **Phase 9 — go/no-go decision**：依threshold與STOP rule，不得post-result tuning。
11. **Phase 10 — only after PASS**：Real40與broader product tests；production enablement仍需explicit authorization。

每階段都必須保留 stable IDs、ownership、revision、atomicity、history、firewall、fail-closed與deterministic rendering。

## 30. Approval Status

`APPROVED_PROJECT_GOVERNANCE`

本文件的`POLICY-16`及`POLICY-18`–`POLICY-22`已和其餘五份文件同步。本次治理工作未修改production code、tests、database、runtime prompt或既有應用行為。

`GOVERNANCE RECONCILIATION STATUS = COMPLETE`

`RUNTIME IMPLEMENTATION AUTHORIZED = YES, BUT ONLY IN A SEPARATE FUTURE IMPLEMENTATION TASK.`

既有Phase 1–3B成果不在本治理修訂重作。Phase 3B.1 offline及D1–D2 checkpoints已完成；既有D3 `claimed_literal=五位`、`canonical_value=5`依narrow Count boundary為`PASS AS SEMANTICALLY ACCEPTABLE`，不需重跑provider。Exact next checkpoint是human manual D4，之後仍須D5；D4/D5完成前及另案授權前不得Phase 4。
