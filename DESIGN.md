# pydwshape — 全链路设计方案（Windows-only · 零网络 · 零额外依赖 · 定稿版）

> 目标：一个可安装的 Python wheel，输入 `(font, text)`，调用 Windows DirectWrite 完成
> shaping，并输出 **feature 级 trace**（每个 feature 相位 + 每次 lookup 应用后的字形快照），
> 语义与 HarfBuzz stage 对齐，供字体开发者对比 DWrite / HarfBuzz 行为。
>
> **平台：仅支持 Microsoft Windows（10/11）。**
> 本库 trace 的是 Windows 系统组件 `dwrite.dll` / `TextShaping.dll` 的 shaping 行为；
> 这些组件**只存在于 Windows**，且不可被重新分发或移植到 macOS / Linux（技术上 PE+Windows
> 内部依赖无法运行，法律上禁止分发微软组件）。因此本库**不提供任何跨平台支持**，也不考虑
> “打包 dwrite 跨平台调用”这类方案。macOS / Linux 上的同类 trace 请直接使用 HarfBuzz。
>
> **设计基线（本版定稿）**
> - 运行时 **只依赖 `frida` + `dwriteshapepy` + Python 标准库**，无任何其它第三方库。
> - **绝对零网络**：不发起到 msdl/任何外部 URL 的请求。符号供给改为**离线 RVA 注册表**。
> - 不改写/不重新分发任何微软二进制或 PDB。
>
> 核心解码已在 `drite` 工作区验证完毕，新仓库无需重新逆向（§4 可直接照用）。

---

## 0. 可行性结论 ✅

已在本机（Windows + Python 3.13）完整验证全链路技术点：

| 技术点 | 状态 | 证据 |
|---|---|---|
| DWrite 复杂文种 shaping 的位置 | ✅ 确认 | 在 `TextShaping.dll`（`dwrite.dll` 委托） |
| 进程内 hook 内部函数 | ✅ 实测 | Frida hook `ApplyFeatures`/`ApplyLookup` 成功 |
| 读 feature 名 | ✅ 实测 | `[locl ccmp nukt akhn]`、`[init medi fina]`、`[rlig …]` 等 |
| 读逐 lookup 字形快照 | ✅ 实测 | 每次 lookup 的 gid 序列 + 变化标注 |
| 终态与 HarfBuzz 一致 | ✅ 实测 | hudum.otf+`ᠰᠠᠢᠬᠠᠨ` 两引擎都到 `[675,281,303,471,281,351]` |
| 零网络地址解析 | ✅ 设计 | §5 离线 RVA 注册表 + 字节特征校验 |
| 零额外依赖打包 | ✅ 设计 | §8；仅 frida + dwriteshapepy |

### 0.1 平台边界（给维护者，避免重复讨论）

- 本库是 **Windows-only**：它观测的是 Windows 专有引擎（DirectWrite→TextShaping）。
- 为什么不能跨平台 / 不能打包 dwrite：
  1. `dwrite.dll`/`TextShaping.dll` 是 Windows PE，依赖 `ntdll/kernel32/OLE32/gdi32` 与系统字体
     服务，在 macOS/Linux 上无法执行，也不存在兼容层。
  2. 微软许可**禁止分发 Windows 组件**——打入 wheel 属明确违规，不做。
- macOS / Linux 用户的同类需求：交给 HarfBuzz（跨平台、开放），本库不承担。
- 判定：任何“把 dwrite/TextShaping 打包进包、让其它系统调用”的提案 → 直接否决（见上）。

---

## 1. 背景：为什么 shaping 在 TextShaping.dll

DirectWrite 排版/渲染在 `dwrite.dll`，但**复杂文种**（阿拉伯、蒙古文等）的 OpenType shaping
委托给系统另一 DLL：

```
Python ──dwriteshapepy──▶ dwrite.dll (IDWriteTextAnalyzer)
                              DWriteTextAnalyzer::GetGlyphs           ── 字符→字形（GSUB）
                                  └▶ TextShaping.dll!ShapingGetGlyphs ── 真正逐 feature/lookup 替换
                              DWriteTextAnalyzer::GetGlyphPlacements  ── 定位（GPOS）
                                  └▶ TextShaping.dll!ShapingGetGlyphPositions
```

`TextShaping.dll` 内部是微软 **OTLS（OpenType Layout Services）** 引擎，每 shape 一次：
约 26 个 `ApplyFeatures`（feature 相位）+ 约 86 次 `ApplyLookup`（逐 lookup 应用）。

---

## 2. 目标 API

```python
from pydwshape import trace_directwrite, DirectWriteTracer

# 一次性
result = trace_directwrite(font=r"D:\...\hudum.otf", text="ᠰᠠᠢᠬᠠᠨ", features=None)

# 或复用进程（多次 shape 更快）
with DirectWriteTracer() as tr:
    for txt in texts:
        r = tr.shape(font, txt)
```

`TraceResult`（dataclass）大致为：

```python
@dataclass
class LookupEvent:
    index: int
    table: str  # 'GSUB' / 'GPOS'
    glyphs: list[int]  # 应用后字形序列（全数组）
    changed: list[tuple[int, int, int]] | None  # [(pos, old, new), ...] 或 None=无变化


@dataclass
class FeaturePhase:
    index: int
    table: str
    features: list[str]  # 该相位应用的 feature tag 集
    lookups: list[LookupEvent]


@dataclass
class ShapeRun:
    index: int
    feature_phases: list[FeaturePhase]


@dataclass
class TraceResult:
    upem: int
    final_glyphs: list[int]
    glyph_names: dict[int, str]  # 来自 dwriteshapepy font.glyph_to_string
    runs: list[ShapeRun]
    meta: dict  # 引擎 build、地址来源(symbol/rva)、耗时
    raw_events: list[dict]  # agent 原始事件，便于排查
```

---

## 3. 架构总览

```
┌────────────────────── 主进程（调用方） ──────────────────────┐
│ pydwshape.api                                             │
│   DirectWriteTracer.shape(font,text) ──▶ TraceResult          │
│      │                                                         │
│      ├─ orchestrator.py                                       │
│      │   • spawn worker（sys.executable -m pydwshape.worker）│
│      │   • 等 worker READY（已 warm-up，TextShaping.dll 已加载） │
│      │   • addr_resolve：按 TextShaping 版本挑 RVA 表+特征校验   │
│      │   • frida.attach(pid) → 载入 agent.js（用解析到的地址）  │
│      │   • 发 shape 命令 → 收事件 → 组 TraceResult             │
│      │   • close(): detach + 结束 worker                       │
│      │                                                         │
│      └─ addr_resolve.py（零网络）                              │
│          • 读 TextShaping.dll 文件版本（VersionInfo，stdlib）   │
│          • RVA 注册表：{版本/版本族: {ApplyFeatures:RVA, ...}}   │
│          • attach 后对 base+RVA 做字节特征校验；不匹配→报清晰错  │
│          • （可选）若用户本地已有匹配 PDB 且设了符号路径→优先符号 │
└────────────────────────────────────────────────────────────────┘
        │ frida message                    │ stdin/stdout: JSON 行
        ▼                                  ▼
┌──────────────────── worker（子进程） ────────────────────┐
│ worker.py                                                 │
│   • import dwriteshapepy（加载 dwrite.dll）                │
│   • warm-up shape → print("READY")                        │
│   • 循环读 stdin JSON: {cmd:"shape",font,text,features}   │
│        dw.Face→dw.Font→dw.shape(...)                      │
│     stdout JSON: {ok,glyphs:[...],upem}                    │
└───────────────────────────────────────────────────────────┘
```

**为什么子进程 + Frida 双进程？** Frida hook 的是 worker 进程内部的 `TextShaping.dll`；
主进程不能 hook 自己，子进程充当稳定"被观察对象"。

---

## 4. 已解码的内部结构（新仓库的"金矿"，勿再逆向）

> PDB 里这些 otl*/SHAPING_* 类型是空壳（微软剥离布局）。下列为 Frida 读内存 + Ghidra
> 反编译交叉验证的**运行时布局**。

### 4.1 通用列表 otlList / otlFeatureSet
```
struct otlList {
    void* data;     // +0x00  8B 元素数组指针
    u16   elemSize; // +0x08
    u16   count;    // +0x0c
};
```
`otlFeatureSet` 同式（首字段指向 feature 记录数组）。

### 4.2 ApplyFeatures —— feature 相位
```c
int ApplyFeatures(
    int tag,               // args[0] 'GSUB'(0x42555347)/'GPOS'(0x534f5047)
    otlFeatureSet* fs,     // args[1] 本次要应用的 feature 集
    otlList* p3, otlList* p4, otlResourceMgr* rm,  // args[2..4]
    int scriptTag,         // args[5] 'mong'
    int langTag,           // args[6] 'ZHS '
    ...);
```
读取：`count=u16(fs+0x0c); rec=u16(fs+0x08); data=*(u64*)fs`；
第 i 个 feature **tag = u32 @ data+i*rec**（host 小端 → 4CC）。一个相位 = 一组 feature 一起应用。

### 4.3 ApplyLookup —— 逐 lookup 字形快照
```c
int ApplyLookup(int tag, otlList* glyphIdx /*args[1]*/,
                otlList* glyphs /*args[2] ★*/, otlResourceMgr*, otlLookupTable*, ...);
```
字形记录 rec=8（4×u16）：`[ gid@+0 ][ flags@+2 ][ idx@+4 ][ ?@+6 ]`。
读取：`count=u16(glyphs+0x0c)`；第 i 个 gid = `u16(*(u64*)glyphs + i*8)`。
**count 会在分解/插入虚形时增长再回落**，不要假设长度固定。

### 4.4 运行括号与完成信号
- `TextShaping!ShapingGetGlyphs`（导出）enter=GSUB 开始 / leave=GSUB 结束。
- `TextShaping!ShapingGetGlyphPositions`（导出）enter/leave=GPOS 开始/结束。
- 一次 `dw.shape()` = 一次 GSUB + 一次 GPOS；**以 `gpos_end` 作为一次 shape 完成信号**。
- 复杂文本可能多次 GetGlyphs → 事件按 run 分组，一个 gpos_end 内所有 run 归为一次 shape。

### 4.5 黄金用例（测试断言）
hudum.otf + `ᠰᠠᠢᠬᠠᠨ` → 两引擎终态 `[675,281,303,471,281,351]`。关键替换点：
```
init : 673→675
medi : 277→281  295→302  461→464  277→281
fina : 350→351
rclt :（插虚形 273/274/275 再 ligate 掉）内 464→471 ; 302→303
```

---

## 5. 零网络地址解析（核心机制，替换原 PDB 下载方案）

`ApplyFeatures` / `ApplyLookup` **不是导出函数**，Frida 无法用 `enumerateExports` 找到。
在不联网的前提下，用**离线 RVA 注册表 + 字节特征校验**解决：

### 5.1 RVA 注册表（仓库内数据文件，随包分发）
```jsonc
// rva_registry.json（示例）
{
  "windows": {
    // key = TextShaping.dll 的 FileVersion 主段，如 "10.0.19041"
    "10.0.19041": {
      "sha256_prefix": "a1b2c3...",          // 可选，更严的 build 标识
      "ApplyFeatures": 0x15650,
      "ApplyLookup":   0x7A60
    },
    // 同版本族可共享（微版本差异一般不影响这些内部函数 RVA）
    "10.0.22621": { "ApplyFeatures": 0x?????, "ApplyLookup": 0x????? }
  }
}
```
- 本机实测：`ApplyFeatures ≈ base+0x15650`，`ApplyLookup ≈ base+0x7A60`
  （对应某 Win10/11 的 TextShaping；见 `tools/ghidra/` 的重测步骤，新系统只需补一行表）。
- 读取 TextShaping 文件版本：`C:\Windows\System32\TextShaping.dll` 的
  `FileVersionInfo`（`ctypes.windll.version` 或纯 `struct` 解析 PE 资源均可，stdlib 实现）。

### 5.2 解析顺序（agent / orchestrator 一致）
```
1) 若目标进程 env 设了符号路径且本地有匹配 PDB → enumerateSymbols 按名解析（可选项，非默认）
2) 否则：注册表按版本查 RVA → 地址 = TextShaping.base + RVA
3) attach 后对每个候选地址做「字节特征校验」：读前 8~16 字节与已知特征比对
   （特征从 Ghidra 反编译/本机实测取；每个版本存一小段签名）
   —— 校验通过才 hook；失败则报「该系统 TextShaping 版本不受支持，请向 tools/ghidra 补充注册表」
4) 绝不盲 hook：宁可报错也不在错误地址装 hook
```

### 5.3 为什么这样能"零网络 + 零依赖"且可维护
- 地址来自**包内静态表**，不依赖任何外部查询 → 零网络。
- 解析只用 stdlib（读文件版本）+ 包内 JSON → 零额外依赖。
- 覆盖面靠"表 + 签名"增长：每支持一个新 Windows 版本，只需在开发机上用
  `tools/ghidra`（或本项目已给的导出脚本）跑一次反编译，把 `ApplyFeatures/ApplyLookup`
  的 RVA + 前几条指令特征追加进 JSON（不改代码）。
- PDB 不再是运行时依赖；若用户**本地恰好有匹配 PDB** 并可设 `_NT_SYMBOL_PATH`，
  才作为可选增强路径（第 1 步），不联网、非必需。

---

## 6. 关键实现细节与协议

### 6.1 worker（子进程）
- 由 orchestrator 以 `sys.executable -m pydwshape.worker` 启动。
- 启动：`import dwriteshapepy` → 做 **1 次 warm-up shape**（触发 dwrite/TextShaping 加载）→
  `print("READY")`(flush)。
- 主循环读 stdin JSON 行：
  ```json
  {"cmd":"shape","font":"C:\\...\\hudum.otf","text":"...","features":null}
  ```
  读字体 bytes → `dw.Face`→`dw.Font`→`Buffer.add_str`→`dw.shape`→stdout JSON 结果(flush)。
- stdin EOF → 退出。worker 只负责被观察，不自己 trace。

### 6.2 agent（frida）事件协议
`agent.js`（仓库已有骨架，直接可用），全部用 `send()` 结构化事件：
```jsonc
{t:"hello", base, size, engine_build}
{t:"run_start", run}
{t:"feature", run, phase, table, count, features:[...]}
{t:"lookup",  run, n, table, glyphs:[...], changed:[[pos,old,new],...]|null}
{t:"run_end", run}
{t:"gpos_start", run}
{t:"gpos_end", run}      // ← 一次 shape 完成
{t:"fatal", msg}
```
用 `script.on("message")` 接收 payload（不要解析 console.log）。

### 6.3 orchestrator
```
start():
  proc = Popen([sys.executable,"-m","pydwshape.worker"], stdin=PIPE, stdout=PIPE)
  读 stdout 首行 == "READY"（超时）
  build   = addr_resolve.detect_textshaping_build()      // 读 System32 文件版本
  addrs   = addr_resolve.resolve(build)                  // 注册表 RVA（+可选符号）
  session = frida.attach(proc.pid)
  script  = session.create_script(agent_js, 需注入 addrs)
  script.on("message", on_msg); script.load()
  等 {t:"hello"}（agent 内对 addrs 做特征校验 → 失败发 fatal）

shape(font,text,...):
  events.clear()
  写 shape JSON → 收事件直到 gpos_end（或超时）→ 读 worker stdout 一行 ack
  → 组 TraceResult（含 glyph_names=worker 或 dwriteshapepy.glyph_to_string）→ 返回

close():
  script.unload(); session.detach(); stdin.close(); proc.wait(timeout)
```

### 6.4 健壮性
- worker 单线程串行，避免事件交错。
- 字形 count 变化 → trace 存全数组，changed 只对等长相邻快照给。
- 超时/崩溃可重试；close() 不留残留进程。
- agent 事件带 run/序号，orchestrator 按 gpos_end 切分。

---

## 7. 仓库结构

```
pydwshape/
├─ pyproject.toml              # 仅依赖 frida + dwriteshapepy；package-data 含 agent.js/rva_registry.json
├─ README.md                   # 使用、支持范围（Windows + TextShaping 版本）、免责/NOTICE
├─ NOTICE                      # 致谢 frida、microsoft/DWriteShapePy；声明非微软产品、无背书
├─ LICENSE                     # MIT
├─ src/pydwshape/
│  ├─ __init__.py              # 导出 trace_directwrite / DirectWriteTracer
│  ├─ api.py                   # 公开 API + TraceResult dataclasses
│  ├─ orchestrator.py          # 进程 + frida 编排
│  ├─ worker.py                # 子进程（python -m pydwshape.worker）
│  ├─ agent.js                 # frida hook 脚本（结构化 send）★已写好
│  ├─ addr_resolve.py          # 零网络：版本检测 + RVA 注册表 + 特征校验（替代原 symstore）
│  ├─ rva_registry.json        # 版本→{ApplyFeatures,ApplyLookup,RVA,签名}
│  ├─ decode.py                # §4 布局常量与解码辅助（tag4/u16/u32/otlList 读取）
│  └─ _version.py
├─ tests/
│  ├─ test_golden_mongolian.py # hudum.otf+ᠰᠠᠢᠬᠠᠨ → 断言 [675,281,303,471,281,351]
│  └─ test_api.py
└─ tools/ghidra/
   ├─ export_decompiled.java   # headless 反编译（复用 drite 已验证脚本）
   └─ README.md                # 新系统补充 RVA 注册表的标准步骤
```

---

## 8. 构建 wheel

`pyproject.toml` 要点：
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pydwshape"
version = "0.1.0"
requires-python = ">=3.9"
# Windows-only：macOS/Linux 不装（DirectWrite 不存在于这些平台）
dependencies = [
    "frida>=15.0; platform_system == 'Windows'",
    "dwriteshapepy>=1.0.10; platform_system == 'Windows'",
]
classifiers = [
    "Programming Language :: Python :: 3",
    "Operating System :: Microsoft :: Windows",
    "Topic :: Text Processing :: Fonts",
]

[tool.setuptools]
package-dir = {"" = "src"}
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
pydwshape = ["agent.js", "rva_registry.json"]
```
构建：`python -m build` → `dist/dwrite_shape_trace-*.whl`（纯 Python+数据，仅 Windows 可用）。

---

## 9. 验证 / 验收清单

1. **黄金用例**：`trace_directwrite(hudum.otf, "ᠰᠠᠢᠬᠠᠨ")` →
   - `final_glyphs == [675,281,303,471,281,351]`
   - feature 相位含 `init/medi/fina` 与 `rlig`；能找到 `673→675`、`350→351` 等变化
2. **零网络**：断网环境跑通（注册表路径）；agent 不发任何 HTTP
3. **零额外依赖**：全新 venv 仅装 `pydwshape`（自动带 frida+dwriteshapepy）可 import 并跑
4. **其它用例**：阿拉伯文、纯拉丁、不同字体
5. **健壮性**：不支持的 TextShaping 版本 → 清晰报错 + 指引补充注册表；worker 崩溃可重试
6. **打包**：`pip install dist/*.whl` 后从任意目录可用（agent.js/json 在包内）

---

## 10. 风险与注意

| 风险 | 说明 | 缓解 |
|---|---|---|
| 版本相关 | 内部函数 RVA 随 TextShaping 版本变 | 注册表按版本分桶 + 字节特征校验；不支持就明确报错并给补表步骤 |
| 字节特征脆弱 | 签名若遇编译器变更 | 校验只作"防止盲 hook"的安全网；主键是文件版本 |
| frida attach 兼容 | 个别环境受限 | 捕获异常给清晰错误；目标仅自建 worker，无对抗 |
| 多 run 文本 | 一次 shape 多次 GetGlyphs | 事件按 run 分组，gpos_end 界定一次 shape |
| 字形数变化 | 分解/ligature 改变 count | trace 存全数组快照，diff 由上层做 |
| 平台 | 仅 Windows | pyproject 标注 + README 说明 |
| 授权 | 涉及微软内部函数观察 | 见 DESIGN 附录 A（已评估：只读观察 + 公开 API 互操作，低风险） |

---

## 11. 新仓库落地步骤（Roadmap）

1. 脚手架：§7 目录 + pyproject + LICENSE/NOTICE/README；`pip install -e .`
2. **worker**（§6.1）：起子进程、warm-up、READY、响应 shape
3. **addr_resolve**（§5）：读 TextShaping 版本 → RVA 注册表命中（先内置本机实测两行）
4. **agent**（已给 agent.js）：注入地址、装 hook、hello + 特征校验
5. **orchestrator**（§6.3）：attach + 事件收集 → TraceResult
6. **golden 测试**（§9.1）：hudum.otf 蒙古文通过 = 全链路 OK
7. 打包 + 验收清单其余项
8. （可选）与 babelmap/harfbuzz 对照输出

---

## 附录 A：PyPI 合规要点（已评估）

- 不打包任何微软二进制/PDB（本设计零网络，PDB 仅本地可选）。
- 驱动公开 API（IDWriteTextAnalyzer via dwriteshapepy）+ 对内部函数**只读观察**，
  类同 profiler/debugger；无 DRM 绕过、无改写、无再分发。
- 依赖：frida = wxWindows Library Licence（独立依赖，无传染）；dwriteshapepy = MIT。
- 中性包名、README 声明"非微软产品、无微软背书"、附 NOTICE 致谢。

---

> 可直接搬运的文件（`D:\System\Desktop\drite\pydwshape\`）：
> - `pyproject.toml`（骨架，按 §8 补全）
> - `src/pydwshape/agent.js`（frida agent，结构化事件）
> 解码结论（§4/§5）与黄金用例（§4.5）见会话记忆，可随时调出。
