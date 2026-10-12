# DY-spark

每天给你在意的人发一条消息，让抖音聊天火花（连续聊天天数）不掉——命令行运行，跑在你自己的机器上，用你自己的账号。

```
python -m dspark login        # 扫一次二维码
python -m dspark scan         # 列出每个会话，以及有没有火花
python -m dspark send         # 空跑：只列出会发给谁，不发送
python -m dspark send --yes   # 真正发送（打字文案）
python -m dspark send --yes --emoji   # 改发表情面板里的「续火花」表情
```

抖音改版时用的排查工具：

```
python -m dspark edge         # 开一个带调试端口的浏览器
python -m dspark pick         # 点页面元素，直接得到它的选择器
python -m dspark probe        # 把整个页面 dump 下来
python -m dspark analyze      # 离线从 dump 里推断选择器
```

嫌麻烦可以直接双击 `scan.bat`：它会自动把浏览器准备好 → 扫描 → 问你要怎么做：

```
       0  =  输入文字发送
       1  =  退出，什么都不发
       2  =  发送抖音表情面板里的「续火花」表情
```

---

## 请先读这一节

抖音的聊天页需要登录才能看到，所以本项目里的一切都是从**真实页面上读下来的**，而不是猜的。但各部分的确信程度不一样：

| 部分 | 状态 |
|---|---|
| 浏览器层：启动、会话 cookie、`storageState`、截图 | **已实测**（针对真实的 douyin.com） |
| 登录状态判断（已登录 / 未登录） | **已实测** —— 未登录时能正确报告 |
| 首页钩子：消息入口、登录按钮 | **已实测** |
| 会话行与火花徽标 | **已实测** —— 标记从 DevTools 原样抄下来，见下 |
| 输入框（Slate 编辑器） | **已实测** —— 标记从 DevTools 原样抄下来，见下 |
| 表情面板、表情按钮、发送按钮 | **已实测** —— 面板能打开、23 个表情的标签能读出、「续火花」能按名字选中，见下 |
| 配置加载与校验、错误信息 | **已实测** —— 每条失败路径都有测试 |
| 空跑、限速、两道开关、变体过滤 | **已实测** —— 82 个离线测试 |

现在每一个选择器都来自真实页面。**唯一没有验证的是"交互"本身**：Slate 编辑器是否接受合成键盘事件。所以 `_send_to` 会在按下回车前**把输入框内容读回来核对**，如果文字没进去就明确报告，而不是谎报一条根本没发出的消息。

> **抖音的用户协议并不欢迎自动化。** 本工具只会用*你自己的账号*，给你*本来就在聊*的人发消息，而且刻意做得很慢——但一个火花不值得拿账号去赌。建议先跑几天 `scan` 和空跑的 `send`，确认可靠再正式用。

### 真实页面结构长什么样

会话行，从已登录的 `douyin.com/chat` 的 DevTools 里抄的：

```html
<div data-e2e="conversation-item" class="conversationConversationItemWrapper">
  <div class="conversationConversationItemrowArea1">
    <div class="commonIMAvataravatarContainer">
      <span class="semi-avatar semi-avatar-circle ...">
        <img src="https://p26.douyinpic.com/img/aweme-avatar/...">
      </span>
    </div>
  </div>
  <div class="conversationConversationItemrowArea2">
    <div class="conversationConversationItemtitle">张三</div>
    <div class="commonStreakstreakContainer">
      <img class="commonStreakicon"
           src=".../flame_icon/normal/gray_normal.png" alt="">
      <div class="commonStreaknormalText"> 129 </div>
    </div>
  </div>
</div>
```

从这段标记里能得出六件事，每一件都是踩出来的：

1. **会话行带 `data-e2e="conversation-item"`。** 这就是行选择器，而且稳定。

2. **火花天数就在标记里**（`commonStreaknormalText` → `129`）。`scan` 会把它打印出来，这样"识别对不对"就变成了**用眼睛能核对**的事，而不是只能相信一个是/否标志。

3. **灰色的火花对应 129 天的连续天数。** 这是最大的陷阱：**灰色只是列表里的普通显示状态，不代表没有火花**。所以三种火焰图标（`normal_normal`、`blue_normal`、`gray_normal`）默认**都算**；如果你不认同，可以用 `sending.spark_variants` 收窄。

4. **列表是虚拟化的。** `/chat` 在 DOM 里只保留大约一屏的行，滚动时**复用**这些节点。所以"读一次"拿到的是**列表的一个窗口，不是列表本身**——最早能跑的版本读到 13 个会话，并且**非常自信地**把它当成了全部。现在的做法是滚到底、沿途收集，并按头像 URL 去重（节点被复用之后，行号就毫无意义了）。在开发用的那个账号上，这个改动把数量从 13 变成了 42。

   滚动是用 JavaScript 做的，而不是 `locator.scroll_into_view_if_needed()`——因为后者要等元素"稳定"，而虚拟列表里**正被滚动的那一行恰恰就是会被回收的那一行**。它会在滚动中途报错，从而**悄悄截断结果**。

5. **滚动位置会被记住。** 抖音会把列表的滚动位置跨刷新恢复，所以一个停在底部的页面重新加载后**还是在底部**。更隐蔽的是：把 `scrollTop` 设成 0 **并不会让虚拟列表重新渲染**，DOM 里短时间内还是旧位置的那些行。最初"回顶部"的写法因此收走了**列表尾部**，而最前面 9 个会话从头到尾没被看见过。现在回顶部后要**盯着首行直到它真的变了**才算数。

6. **发送流程有它自己的版本。** 扫描结束时列表停在底部，而查找某个好友**只往下走**——所以第一次真实运行对靠前的九个好友全部报了 `Could not find '某位好友' in the list`。现在每次查找前都回顶部，而且**扫两遍**：某次扫描找到 29 个里的 26 个，下一次同样的代码找到 29 个——这种偶发失败在这个循环里等于"某个人的火花断掉"，不能接受。

   还有：**一次滚动半屏，不是大半屏。** 虚拟列表渲染的行数可能少于一屏，0.85 屏的跳跃会**整段跳过**一批会话——这就是"明明在列表里的人却被报告找不到"的原因。

输入框同理，从 DevTools 抄的：

```html
<div data-e2e="msg-input" class="messageMsgInputcontainer">
  <div class="messageMsgInputinputRow">
    <div class="zone-container editor-kit-container messageEditorinputArea ..."
         data-slate-editor="true"
         contenteditable="true"
         data-placeholder="发送消息">
      <div class="ace-line" data-node="true" dir="auto">
        <span data-leaf="true">&#8203;</span>
      </div>
    </div>
  </div>
</div>
```

**它是 Slate.js 编辑器，不是 textarea。** 由此带来三个后果，代码里都处理了：

| 后果 | 代码怎么处理 |
|---|---|
| `fill()` 对 Slate 编辑器**完全无效** | 先点击聚焦，再发送真实键盘事件 |
| 空的输入框里仍有一个零宽空格（U+200B） | `_COMPOSER_JS` 在判断空之前先剥掉 `[\u200b-\u200d\ufeff]` |
| Slate **可能**拒绝合成输入 | `_send_to` 会读回输入框内容，文字没进去就拒绝按回车 |

第二条是一个**差点上线的真 bug**：JS 的 `String.trim()` **不会**去掉 U+200B，所以每一次成功发送都会被误判为失败，然后还会去点一个毫无意义的备用发送按钮。现在有专门的测试钉住这段转义——因为**少写一个反斜杠**就会把 `[\u200b-…]` 变成 `[u200b-…]`，那就变成了匹配字母 u、2、0、b。

输入区右侧的三个控件，以及表情面板，同样抄自 DevTools：

```html
<div class="messageMsgInputinputAction">
  <div class="semi-upload MsgInputFileuploadim-saas-fileUploader">…</div>
  <svg class="messageMsgInputiconAction">…</svg>                    <!-- 😀 表情按钮 -->
  <svg class="messageMsgInputpublishBtn e2e-send-send-msg-btn">…</svg>  <!-- ↑ 发送按钮 -->
</div>

<div class="componentsemojiemojiPanel">                            <!-- 表情面板 -->
  <div class="emojiEmojiItememojiItem">
    <div class="emojiEmojiItememojiImgBox" data-apm-action="EmojiItem">
      <img class="commonMyImageimgReal" src="…">
    </div>
    <div class="emojiEmojiItememojiItemDesc">续火花</div>            <!-- 文字标签 -->
  </div>
</div>
```

三点值得注意：

1. **发送按钮是 `<svg>`，不是 `<button>`。** 原来的 `SEND_BUTTON` 只找 `button` 元素，所以**永远匹配不到任何东西**——回车失效时的备用路径其实是一段死代码。现在有了真实的选择器 `e2e-send-send-msg-btn`。

2. **每个表情都带文字标签**，所以可以按名字选，而不是按位置。`[class~="emojiEmojiItememojiItem"]` 用的是精确词匹配（`~=`）而不是子串匹配（`*=`）——因为子串形式**也会匹配到 `emojiEmojiItememojiItemDesc`**，那是标签本身，不是表情。

3. **面板是模态弹窗，打开时会拦截整页点击**，而且它的遮罩连自己的切换按钮都盖住。用 `document.elementFromPoint` 对准按钮坐标量过：`onTop: div.semi-modal-wrap`。Escape、点按钮、JS 派发点击全都无效，**只有重载页面能清掉**。

登录流程相关的标记，同样是从真实页面读的：

```html
<!-- 消息入口就是顶栏的「消息」按钮 -->
<div data-e2e="im-entry">
  <div><div data-e2e="something-button">
    <div><i></i></div><p>消息</p>
  </div></div>
</div>

<!-- 登录按钮的 class 是哈希，所以只能用文字定位 -->
<p class="VQdYTqcZ">登录</p>
```

在 DOM 里搜 `class~="login"` 或 `class~="avatar"` **什么也搜不到**——可 `commonStreakicon` 却是个完全可读的类名。这就是关键一课：**抖音同时跑着两套命名系统**。布局用的是 CSS-module 哈希名，每次发布都变；功能级的部件保留可读名，不会变。所以优先级是：`data-e2e` → **可读的**类名 → 永远不要用哈希。

这个过程还暴露了两个坑，代码里都处理了：

1. **未登录时点「消息」入口不会报错。** 抖音会**静默地**把你弹到推荐页（`/jingxuan`）。如果盲目相信这次点击，工具就会去读一个空列表，然后把锅甩给选择器。所以 `_goto_messages()` 会**确认真的到达了**，并告诉你到底是两种原因里的哪一种。
2. 消息页第一次没出现时，工具会**明确说出来**，而不是报告"找到 0 个会话"。

---

## 工作原理

### 1. 登录状态存在 JSON 文件里，不在代码里

会话用 Playwright 自带的 `storageState` 持久化，它把 cookie 和 localStorage 序列化到磁盘。参考项目 [laizan](https://github.com/GHkmmm/laizan) 用的也是这个办法——它的 `ipc/auth.ts` 只有二十来行，核心就这些：

```ts
ipcMain.handle('hasAuth', () => Boolean(storage.get(StorageKey.auth)))
ipcMain.handle('login', async () => { await loginAndStorageState() })
```

所以流程是：浏览器打开**一次**，**你自己**扫码，状态写进 `.session/storage_state.json`，之后每次运行自动注入。**本工具从头到尾见不到你的密码、验证码和手机号。**

### 2. 用 `data-e2e` 定位，而不是类名

抖音的类名是哈希的，每次发布都变，做钩子毫无价值。它真正保留的属性是 `data-e2e`。laizan 也依赖它——它用

```
[data-e2e="feed-active-video"] [data-e2e="feed-comment-icon"]
```

关掉评论面板，用按 `z` 键而不是点击来点赞。**稳定的属性 + 键盘快捷键**，整套技巧就这些。

### 3. 两道开关都同意才会发送

配置里的 `sending.enabled: true` 意思是"这个工具被允许发送"。命令行的 `--yes` 意思是"这次真的发"。**两个都需要。** 不带 `--yes` 的运行会完整打印出"会发给谁、发什么"，然后停下。

---

## 安装

需要 Python 3.10 或更高版本。

```bash
cd DY-spark

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

然后把 Chromium 装**到项目里**，而不是装进用户级缓存，这样整个工具是自包含的：

```bash
# Windows (PowerShell)
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
python -m playwright install chromium

# macOS / Linux
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" python -m playwright install chromium
```

这是一次性的约 700 MB 下载，落在 `DY-spark/.browsers/`（已被 gitignore）。**这个环境变量只需要在安装时设一次**——`dspark/browser.py` 在运行时会自己找到 `.browsers/`，以后不用再 export。

最后：

```bash
cp config.example.yaml config.yaml     # Windows: copy config.example.yaml config.yaml
```

---

## 快速开始

### 步骤 1 —— 登录

```bash
python -m dspark login
```

会弹出一个真实浏览器窗口。用抖音 App 扫码。会话保存好后窗口会自己关闭。

检查是否成功：

```bash
python -m dspark status
```

### 步骤 2 —— 扫描，核对火花识别

```bash
python -m dspark scan
```

不发送任何东西。它会走完整个聊天列表，每个会话打印一行：

```
  #  spark   days  variant             name
---  -----  -----  ------------------  -----
  1  yes      129  gray_normal.png     张三
  2  yes       12  normal_normal.png   李四
  3  -          -  -                   王五
  4  yes        3  blue_normal.png     赵六

[ok] 42 conversation(s) found by scrolling the whole list, 29 with a spark
[i] strategy `spark` matches 29 conversation(s); max_per_run 100 -> 29 would be messaged
[i] Nothing was sent.
```

**继续之前，先把这张表读一遍。** 挑几行跟抖音 App 里显示的对比：如果天数对得上、该标 `yes` 的人确实标了 `yes`，那识别就是准的。不对就去步骤 3。

最后两行是刻意分开的：**匹配到多少**（29）和**这次会发多少**（也 29）。如果 `max_per_run` 小于匹配数，两者会不一样，工具会**大声警告**——因为静默截断意味着有人火花断掉，而运行日志还显示成功。

`variant` 那一列是找到的火焰图片文件名。想跳过某种颜色，就把要保留的列进 `sending.spark_variants`。

### 步骤 3 —— 修选择器（只在步骤 2 看起来不对时做）

两种办法，第一种快得多。

**（a）`pick` —— 点元素，拿选择器。** 推荐：

```bash
python -m dspark pick
```

会打开一个浏览器，左上角有个蓝色徽标。登录、走到消息页，然后点徽标开启拾取。之后你点的每个元素都会在终端里打印它的选择器，最好的排在最前面：

```
[ok] <textarea>  
[i]   textarea[placeholder="发送消息"] <- best
[i]   div[contenteditable="true"]
```

它**永远不会**建议哈希类名。给出的候选按"通常能活多久"排序：

| 顺序 | 类型 | 原因 |
|---|---|---|
| 1 | `[data-e2e="..."]` | 抖音真正在维护的属性 |
| 2 | 祖先的 `data-e2e` + 标签 | 用于图标和内部 span |
| 3 | `#id`、`placeholder`、`aria-label`、`role` | 存在时很稳定 |
| 4 | 其他 `data-*` 属性 | 常是生成的，但一般稳定 |
| 5 | `tag:has-text("...")` | 短可见文本 |

它能跨页面导航存活，因为它是作为 init script 注入的，而不是在某个页面上装一次——所以你可以先登录、到处走一圈，再开始拾取。结果也会存到 `diagnostics/picked-<time>.json`。

**（b）`probe` —— dump 整个页面。** 需要看全貌时用：

```bash
python -m dspark probe
```

会在 `diagnostics/` 里写三个文件：

| 文件 | 是什么 |
|---|---|
| `probe-<time>.png` | 截图——经常光看它就够了 |
| `probe-<time>.html` | 完整 DOM，用于搜索 |
| `probe-<time>.json` | 页面上每一个 `data-e2e` 值 |

然后编辑 `dspark/selectors.py`——*Message page* 下面那几个常量就是标注为未验证的。重跑 `pick` 或 `probe`，直到数量对了为止。

> 如果你**完全找不到**火花徽标，可能是抖音网页版根本不渲染它。这种情况把 `sending.strategy` 设成 `list`，在 `sending.targets` 里写上好友昵称——这样工具就完全不需要读徽标了。

### 步骤 4 —— 空跑

```bash
python -m dspark send
```

打印出**会**发给谁、发什么。不会真的发送。反复跑到名单正好是你预期的人为止。

### 步骤 5 —— 开启并发送

在 `config.yaml` 里：

```yaml
sending:
  enabled: true
```

然后：

```bash
python -m dspark send --yes
```

第一次真实发送时保持 `browser.headless: false`，这样可以盯着看。

### 步骤 6（可选）—— 改发表情

不想打字，就发抖音表情面板里的「续火花」表情：

```bash
python -m dspark send --yes --emoji
```

流程是逐个好友：打开会话 → 点开表情面板 → **按文字标签**找到「续火花」并点击 → 如果它落在输入框里就按发送 → 关闭面板。

几个实现上的要点，都是踩出来的：

| 问题 | 处理 |
|---|---|
| 面板里第几个是「续火花」 | **按标签文字找，不按位置**。抖音会调整面板顺序，位置靠不住。找不到时会把面板里实际有哪些标签打出来，方便你改 `sending.emoji_label`。 |
| 表情点下去是**直接发送**，还是**填进输入框**等发送？ | **实测是直接发送**，输入框始终为空。但**不能靠数量判断**——消息列表**同样是虚拟化的**，发一条新消息会把旧的挤出 DOM，`<img>` 总数根本不变。改成**看最新一条消息**：DOM 顺序是最新在前（列表用 180° 旋转显示），所以直接读 `[data-index]` 的第一个即可。 |
| 面板是个**模态弹窗**，打开时拦截整页点击 | 卡住时必须先清掉，否则下一次点击会话会失败。Escape 无效、点按钮无效（遮罩盖住了按钮，`document.elementFromPoint` 实测 `onTop: div.semi-modal-wrap`）、JS 派发点击也无效——**只有重载页面能清掉**。所以每次打开会话前都会先检查并恢复。中途 Ctrl+C 就会留下这个状态。 |

> **这里踩过一个假阴性**：最初用"数消息列表里的图片数"来判断是否发出，结果**真实发出去了却报告失败**——因为虚拟列表把旧消息挤出去，总数不变。这条经验值得记住：**在虚拟列表上做计数，得到的结论是不可靠的。**

> 重载页面每个好友要几秒。如果抖音选完表情后自己关掉面板，这一步就不会触发；只有面板留着的那些才会重载。

---

## 配置

| 键 | 含义 |
|---|---|
| `session_file` | 登录状态存在哪。删掉它会强制重新扫码。 |
| `browser.headless` | `false` 会显示窗口。调试期间保持可见。 |
| `browser.cdp_url` | 接管已运行的浏览器，例如 `http://127.0.0.1:9222`；留空则自己启动一个 |
| `browser.typing_delay_ms` | 每个按键的随机延迟 `[最小, 最大]` |
| `browser.slow_mo_ms` | 放慢每一个 Playwright 动作 |
| `douyin.navigate_via_home` | `true` 从首页点进消息；`false` 直接访问 `messages_url`（默认） |
| `sending.enabled` | 发送总开关 |
| `sending.strategy` | `spark`（只发有火花的）· `list`（只发 `targets` 里的）· `all`（所有人） |
| `sending.spark_variants` | 哪些火焰图标算数；留空 = 三种全算 |
| `sending.targets` | 好友昵称，供 `list` 策略使用 |
| `sending.messages` | 每个好友随机挑一条（`--emoji` 时用不到） |
| `sending.emoji_label` | 表情模式要发哪个表情，按面板上的文字标签匹配（默认 `续火花`） |
| `sending.delay_between_ms` | 两个好友之间的随机间隔 `[最小, 最大]` |
| `sending.max_per_run` | 单次硬上限，不管策略选中了多少 |
| `logging.verbose` | 打印每一个页面动作 |

跑 `python -m dspark config` 可以看到配置实际解析成了什么。

> **关于 `max_per_run`：** 它是防止失控的护栏，不是预算。**请把它设得比你的好友数大**——它截断掉的人是**静默地**丢掉火花的，而日志照样显示成功。一旦它真的截断了，`send` 会大声警告。

---

## 每天自动运行

**Windows —— 任务计划程序。** 新建基本任务，每天，操作选*启动程序*：

- 程序：`C:\path\to\DY-spark\.venv\Scripts\python.exe`
- 参数：`-m dspark send --yes`
- 起始于：`C:\path\to\DY-spark`

**macOS / Linux —— cron：**

```
0 21 * * * cd /path/to/DY-spark && .venv/bin/python -m dspark send --yes
```

两种方式都建议打开 `logging.save_to_file: true`，这样 `diagnostics/dspark-YYYYMMDD.log` 里会留下每次运行的记录。

火花每天只需要一条消息，所以一天一次就够了——跑得更勤只会让你看起来更像机器人。

---

## 目录结构

```
DY-spark/
├── scan.bat                一键：准备浏览器 → 扫描 → 询问（打字 / 表情 / 退出）
├── config.example.yaml     模板；复制成 config.yaml
├── requirements.txt
├── dspark/
│   ├── __main__.py         CLI 入口              (python -m dspark)
│   ├── config.py           加载 + 校验
│   ├── browser.py          Playwright 会话、storageState、拟人化打字
│   ├── selectors.py        所有抖音选择器 —— 出问题就改这个文件
│   ├── analyze.py          离线 DOM 分析：找候选列表、差异点、输入框
│   ├── picker.py           交互式"点元素、拿选择器"
│   ├── cdp.py              启动 / 接管带调试端口的浏览器
│   ├── streak.py           login / status / probe / scan / send
│   └── console.py          输出，并镜像到日志文件
├── tests/                  离线单元测试（不需要浏览器，不需要网络）
├── .session/               你的登录状态（已 gitignore）
├── .browsers/              Chromium 副本（已 gitignore）
├── .edge-profile/          dspark 专用的浏览器 profile（已 gitignore）
└── diagnostics/            probe dump、拾取的选择器、日志（已 gitignore）
```

## 测试

决定*谁会收到消息*的那部分全部有离线测试覆盖：

```bash
python -m unittest discover -s tests -t . -v
```

82 个测试：配置默认值、每一条校验失败路径、三种目标策略（含单次上限）、火花识别的标记固件、CLI 参数解析、CDP 工具函数。**不需要浏览器，也不需要网络。**

---

## 常见问题

| 现象 | 原因与解决 |
|---|---|
| `config file not found` | `cp config.example.yaml config.yaml` |
| `Playwright is not installed` | `pip install -r requirements.txt`，然后 `python -m playwright install chromium` |
| `Could not attach to the browser at http://127.0.0.1:9222` | 端口上没东西在监听。先跑 `python -m dspark edge`，它会开**自己的**浏览器 profile，所以你已经开着的 Edge / Chrome 完全不受影响——**不需要关任何东西**。 |
| 浏览器明明登录了，却报 `Not logged in` | dspark 用的 profile 和你的日常 profile 是分开的，所以需要**单独登录一次**。在 `dspark edge` 打开的那个窗口里登录即可。 |
| `status` 说会话失效了 | 抖音会登出。重新跑 `python -m dspark login`。 |
| `Conversations found: 0` | `CONVERSATION_ITEM` 过期了。跑 `probe` 对比。 |
| 扫描到的会话数远少于实际 | 列表是虚拟化的，滚动可能提前停了。加 `-v` 看 `rewound` / `scroll` 那几行。 |
| `Could not find 'X' in the list` | 搜索没能够到那一行。加 `-v` 看扫描范围；查找会回顶部并扫两遍，所以**持续**找不到说明那一行确实不在它扫描的列表里。 |
| 发给了错误的人 | `CONVERSATION_ITEM` 匹配过宽。用 `probe` 的输出收紧它。 |
| 什么都没发，也没报错 | 输入框选择器不对，或者这个页面需要用发送按钮而不是回车。加 `-v` 看。 |
| 表情模式报 `No emoji labelled ...` | 面板里没有 `sending.emoji_label` 这个名字。加 `-v`，日志会列出面板里**实际有哪些**标签，照抄其中一个即可。 |
| 表情模式点不开面板 | 可能有上一次留下的模态遮罩。工具每次都会先检查并自动重载恢复；如果频繁出现，加 `-v` 看 `the emoji UI will not close` 那几行。 |
| 用了一周突然不工作了 | 抖音改版了。重跑 `probe`；这是改选择器的事，不是重写。 |

任何命令加 `-v` 都能看到每一个页面动作：

```bash
python -m dspark send -v
```

---

## 参考

`data-e2e` 的思路、`storageState` 登录，以及键盘快捷键技巧（`z` 点赞、`ArrowDown` 下一个视频、`x` 关闭面板）都来自阅读 [laizan](https://github.com/GHkmmm/laizan)——一个基于 Playwright 的抖音工具。如果你打算继续扩展本项目，它的 `src/main/elements/douyin.ts` 值得一读。

本项目使用 [MIT 许可证](LICENSE)。
