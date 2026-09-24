# Tiger-LLM-Short-Long-Memory
(以下共花費約40天)

Tiger-LLM-Short-Long-Memory 是一個本機長短期記憶系統原型
- 第3次實作才成功(codex: pro帳號-USD100，大約花費5、6天)。 是將 "https://www.youtube.com/watch?v=XQXMSc0L5DA&t=356s" ，轉為文字    (位於Tiger-LLM-Short-Long-Memory\技術文件\LLM 記憶系統完整技術報告.txt)

          通過"20個測試案例.txt"的手動測試。
		  Tiger-LLM-Short-Long-Memory_系統架構.docx

- 第1次是叫gpt去找20篇LLM記憶相關的論文，去實作，結果失敗。(花費約30天)
- 第2次是google幾篇LLM的短中期記憶文章，結果失敗，其它包含亞馬遜幾篇相關技術文件。
- chatgpt: https://chatgpt.com/share/6ab34b85-2808-83ee-b576-6617cae6416d
- codex: https://chatgpt.com/s/cx_6ab34bbde7f08191a277fe2ae9ddceb2

目標是驗證：

- 可持久化的長期記憶
- Current / Previous / History lineage
- 使用者隔離
- Scalar 與 Collection / Membership 記憶
- 明確的 Confirm / Cancel / stale protection
- SQLite 交易一致性與資料完整性

目前專案同時保留兩條實驗路線：

1. **自然語言 Memory Runtime**：由 LLM 理解使用者語句後操作記憶。

        目前通過"20個測試案例.txt"的手動測試。

2. **Structured Memory V2**：使用明確欄位與 deterministic operation 操作記憶，不依賴 LLM semantic routing。

---

## 目前狀態

### Natural-Language Memory Runtime

已完成並實際測試：

- Scalar 記憶建立與更新
- Current read
- Previous read
- correction / predecessor continuity
- user/session isolation
- clarification / pending safety
- collection / membership 行為
- cross-collection isolation
- long-session memory consistency

近期人工測試已成功驗證：

- 辦公室：`台北 -> 新竹`，Current=`新竹`，Previous=`台北`
- 車色：`白色 -> 黑色`，Current=`黑色`，Previous=`白色`
- 20-case 人工流程完整通過
- hypothetical case：`如果我搬到高雄，我可能會住左營` 不會覆蓋 Current residence，而是保留為可能住處資訊

> 注意：自然語言 semantic interpretation 仍屬 probabilistic behavior，不能視為 deterministic guarantee。

---

### Structured Memory V2

Structured Memory V2 已完成並封版為：

**Validated Structured Memory V2 Local MVP**

已驗證：

- deterministic scalar core
- stable `memory_id` lineage
- `entity_id` / `semantic_key` 分離
- 多 entity 共用同一 semantic key
- A -> B -> C predecessor continuity
- Current / Previous
- idempotent reassertion
- collection / membership
- count-only collection
- cross-collection isolation
- user isolation
- stale / duplicate confirmation protection
- restart persistence
- SQLite integrity validation
- ResourceWarning clean

Structured Memory V2 不依賴 DeepSeek，且不整合失敗的 V2-1A semantic adapter。

---

## 專案結構

主要檔案：

```text
Tiger-LLM-Short-Long-Memory/
├─ app.py
├─ structured_app.py
├─ memory_core.py
├─ memory_runtime.py
├─ memory_answer.py
├─ memory_proposal.py
├─ memory_audit.py
├─ memory_recovery.py
├─ memory_operations.py
├─ memory_release.py
├─ memory_v2/
│  ├─ __init__.py
│  └─ core.py
├─ memory_v2_semantic/
│  ├─ semantic_adapter.py
│  ├─ semantic_models.py
│  └─ semantic_validator.py
├─ structured_ui/
│  └─ index.html
├─ structured_integrity.py
├─ tests/
└─ docs/
```

---

## 環境

- Windows
- Python 3.11.3
- SQLite
- DeepSeek official API（自然語言版）

建議使用既有虛擬環境：

```powershell
D:\0TIGER\6months\PythonAPIDevelopment\venv_multi_query\Scripts\python.exe
```

---

## 啟動自然語言版

在專案根目錄執行：

```powershell
D:\0TIGER\6months\PythonAPIDevelopment\venv_multi_query\Scripts\python.exe .\app.py --db manual_test.db --port 18080
```

瀏覽器：

```text
http://127.0.0.1:18080
```

請使用獨立測試 DB，避免直接操作既有驗收或 release DB。

---

## 啟動 Structured Memory V2

```powershell
D:\0TIGER\6months\PythonAPIDevelopment\venv_multi_query\Scripts\python.exe .\structured_app.py --db structured_memory.db --port 18081
```

瀏覽器：

```text
http://127.0.0.1:18081
```

Structured Memory V2 使用 explicit structured fields + Prepare -> Confirm，所有 authoritative mutation 由 deterministic V2 core 執行。

---

## 測試

### Natural-Language Runtime

```powershell
python -W error::ResourceWarning -m unittest -v test_app.py
```

### V2 Core

```powershell
python -W error::ResourceWarning -m pytest -q tests/test_memory_v2_core.py
```

### Structured Scalar UI

```powershell
python -W error::ResourceWarning -m pytest -q tests/test_structured_app.py
```

### Structured Collection UI

```powershell
python -W error::ResourceWarning -m pytest -q tests/test_structured_collections.py
```

### Structured Release

```powershell
python -W error::ResourceWarning -m pytest -q tests/test_structured_release.py
```

---

## 已知限制

- Natural-language semantic interpretation 不是 deterministic。
- V2-1A natural-language semantic adapter 曾進行 real DeepSeek gate，但 critical semantic accuracy 未達 release threshold，因此未整合。
- Structured Memory V2 可靠，但 UX 比自由聊天更受限。
- 專案目前定位為本機驗證型 MVP，不是 enterprise production deployment。

---

## 專案原則

- 不針對個別 slot / domain 做 case-by-case hardcode。
- History lookup 不應 fallback 到 Current。
- 所有 destructive mutation 必須 fail closed。
- user isolation 與 collection isolation 為硬性要求。
- reassertion 應為 NO_OP，不建立重複 Current 或破壞 predecessor。
- 測試與人工驗收使用獨立 DB。
- 不將 API key、SQLite DB、cache、logs 或其他本機敏感資料提交到 Git。

---

## Release Summary

```text
Deterministic Memory Core      PASS
Natural-Language Runtime       MANUAL ACCEPTANCE PASS
Structured Scalar UI           PASS
Structured Collection UI       PASS
Restart Persistence            PASS
Integrity Validation           PASS
Structured Memory V2 Release   PASS
DeepSeek in Structured V2      NOT REQUIRED
```
