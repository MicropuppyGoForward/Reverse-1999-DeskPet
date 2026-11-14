import os,sys
import re
import json
import time
import requests
import urllib3
import shutil
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
def get_base_dir():
    """获取程序所在的绝对根目录（兼容打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        # 如果被打包成了 exe，返回 exe 所在的目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是源码运行，返回当前脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
# 屏蔽 Chromium 报错
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置区 =================
with open(os.path.join(BASE_DIR, 'setting.txt'), 'r', encoding='utf-8') as f:
    lines = f.readlines()
    if len(lines) < 2:
        print("❌ setting.txt 格式错误，必须有两行（第一行配置，第二行URL）")
        exit(1)

    # 🎯 核心：取第二行作为 URL
    CHAR_URL_BASE = lines[1].strip()

    match = re.search(r'/profiles/([^/?]+)', CHAR_URL_BASE)
    CHAR_NAME = match.group(1).replace('.', '_') if match else "unknown"
# ==========================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://uttu.merui.net/"
}

def download_file(url, save_path, retries=1):
    """音频极速下载版（去掉漫长重试，防止阻塞）"""
    if os.path.exists(save_path) and os.path.getsize(save_path) > 0: return True
    try:
        response = requests.get(url, stream=True, timeout=5, headers=HEADERS, verify=False)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        return True
    except Exception:
        return False

def wait_for_page_ready(page):
    try:
        if page.locator("text='Yes'").first.is_visible(timeout=2000):
            page.locator("text='Yes'").first.click()
    except Exception:
        pass

def fetch_voices_from_current_page(page, save_dir):
    action_sounds = {"hit": [], "pre_battle": [], "born": [], "select_skill": [], "select_unique": [], "skill1": [],
                     "skill2": [], "unique": []}
    idle_chats = {"morning": [], "night": [], "default": []}
    counters = {k: 0 for k in
                ["hit", "pre_battle", "born", "select_skill", "select_unique", "skill1", "skill2", "unique", "morning",
                 "night", "default"]}
    if not os.path.exists(save_dir): os.makedirs(save_dir)

    download_tasks = []
    fetched_urls = set()
    subtitles_dict = {}  # 👈 新增：收集字幕

    try:
        # 🎯 核心修复：强制等待 DOM 刷新，并且只选取在屏幕上可见的图标！
        page.wait_for_timeout(3500)
        page.wait_for_selector(".voice-play-icon:visible", state="attached", timeout=60000)

        icons = page.locator(".voice-play-icon:visible")
        icons_count = icons.count()

        # 只有默认语音需要预热，专属语音不需要（可以通过目录名判断）
        if "default" in save_dir.lower():
            if icons_count > 0:
                print("  🔥 正在预热音频引擎...")
                icons.first.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
                page.wait_for_timeout(2000)

        for i in range(icons_count):
            locator = icons.nth(i)
            data = locator.evaluate("""el => {
                            let current = el;
                            let title = "Unknown";
                            let subtitle = "";
                            for(let i=0; i<8; i++) {
                                if(!current.parentElement) break;
                                current = current.parentElement;

                                let span = current.querySelector('span');
                                if(span && span.innerText.trim().length > 0 && title === "Unknown") {
                                    title = span.innerText.trim();
                                }

                                let textDiv = current.querySelector('.voice-line-text');
                                if(textDiv) {
                                    subtitle = textDiv.getAttribute('data-zh') || "";
                                    break;
                                }
                            }
                            return {title: title, subtitle: subtitle};
                        }""")
            title = data["title"]
            subtitle = data["subtitle"]

            page.last_audio_url = None
            captured = False

            try:
                locator.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
            except Exception:
                pass

            page.wait_for_timeout(200)

            if getattr(page, 'last_audio_url', None):
                captured = True
            else:
                if i < 5:
                    page.wait_for_timeout(200)
                    try:
                        locator.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
                        page.wait_for_timeout(500)
                        if getattr(page, 'last_audio_url', None): captured = True
                    except Exception:
                        pass
                else:
                    try:
                        locator.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
                        page.wait_for_timeout(350)
                        if getattr(page, 'last_audio_url', None): captured = True
                    except Exception:
                        pass

            if captured:
                audio_url = page.last_audio_url

                # 🎯 去重判断
                if audio_url in fetched_urls:
                    print(f"  [{i + 1}/{icons_count}] ⏭️ 跳过重复音频: {title}")
                    continue
                fetched_urls.add(audio_url)

                title_lower = title.lower()
                if "attacked" in title_lower or "受击" in title:
                    prefix = "hit"
                elif "pre-battle" in title_lower or "战前" in title:
                    prefix = "pre_battle"
                elif "deployment" in title_lower or "部署" in title or "入场" in title:
                    prefix = "born"
                elif "select incantation" in title_lower or "select 3-star" in title_lower:
                    prefix = "select_skill"
                elif "select ultimate" in title_lower:
                    prefix = "select_unique"
                elif "cast arcane skill ii" in title_lower:
                    prefix = "skill2"
                elif "cast arcane skill i" in title_lower:
                    prefix = "skill1"
                elif "cast ultimate" in title_lower:
                    prefix = "unique"
                elif "extra skill" in title_lower or "特殊" in title_lower:
                    prefix = "extra"
                elif "morning" in title_lower:
                    prefix = "morning"
                elif "night" in title_lower:
                    prefix = "night"
                else:
                    prefix = "default"

                if prefix != "extra":
                    counters[prefix] += 1
                    new_filename = f"{prefix}_{counters[prefix]}.ogg"
                    download_tasks.append((audio_url, os.path.join(save_dir, new_filename)))

                    # 👈 收集字幕
                    if subtitle:
                        subtitles_dict[new_filename] = subtitle

                    if prefix in action_sounds:
                        action_sounds[prefix].append(new_filename)
                    elif prefix in idle_chats:
                        idle_chats[prefix].append(new_filename)
                    print(f"  [{i + 1}/{icons_count}] ✅ 捕获: {title}")
                else:
                    print(f"  [{i + 1}/{icons_count}] ❌ 未捕获: {title}")

    except Exception as e:
        print(f"  ⚠️ 该页面无语音或抓取失败: {e}")

    return {k: v for k, v in action_sounds.items() if v}, {k: v for k, v in idle_chats.items() if v}, download_tasks, subtitles_dict
def main():
    # 🎯 核心修复：如果是打包环境，强制让 Playwright 去它自己所在的目录找内核
    if getattr(sys, 'frozen', False):
        # onedir 模式下，资源都在 _internal 里
        bundled_browsers_path = os.path.join(os.path.dirname(sys.executable), "_internal", "ms-playwright")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers_path
        print(f"🔧 已重定向浏览器内核路径至: {bundled_browsers_path}")
    with sync_playwright() as p:
        print(f"启动浏览器... 目标角色: {CHAR_NAME}")
        print("假若下载角色不完整，考虑过一会儿重新安装。uttu网站可能不稳定。")
        try:
            import tempfile
            # 🎯 核心修复 1：强制给 Chromium 分配一个可读写的临时用户数据目录
            user_data_dir = os.path.join(tempfile.gettempdir(), "playwright_pet_chrome_data")

            # 尝试正常启动
            browser = p.chromium.launch(
                headless=False,
                timeout=60000,  # 🎯 拉长启动超时到 60 秒
                args=[
                    "--use-gl=angle",
                    "--enable-webgl",
                    "--ignore-gpu-blocklist",
                    "--enable-unsafe-swiftshader",
                    "--mute-audio",
                    # f"--user-data-dir={user_data_dir}",  # 👈 解决转圈死等的神器
                    "--no-sandbox",  # 防止某些系统权限导致卡死
                    "--disable-dev-shm-usage"
                ]
            )
        except Exception as e:
            # 如果报错包含 "Executable doesn't exist"，说明没有安装浏览器
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                print("\n⚠️ 未检测到 Playwright 浏览器内核！")
                print("👉 请返回控制面板，点击【安装爬虫引擎】按钮。")
                print("或者打开终端运行: python -m playwright install chromium")
                # 抛出异常，中断程序
                raise RuntimeError("缺少浏览器内核，请先安装。") from e
            else:
                raise e
        # 使用无痕上下文，确保每次抓取都是干干净净的初始状态
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)
        def handle_request(request):
            if "voice.merui.net" in request.url and request.url.endswith(".ogg"):
                page.last_audio_url = request.url

        page.on("request", handle_request)

        current_real_model_url = None

        def handle_model_response(response):
            nonlocal current_real_model_url
            url = response.url
            if "model.merui.net/chibi/" in url and url.endswith(".skel"):
                current_real_model_url = url

        page.on("response", handle_model_response)

        # === 1. 抓取技能图标 ===
        print(f"加载主页: {CHAR_URL_BASE}")
        page.goto(CHAR_URL_BASE, wait_until="commit", timeout=30000)
        page.wait_for_timeout(4000)
        wait_for_page_ready(page)

        print("\n准备抓取技能图标...")
        skill_url = f"{CHAR_URL_BASE.split('?')[0]}?page=info&tab=skill"
        page.goto(skill_url, wait_until="domcontentloaded", timeout=60000)
        skills_data = [];
        icon_urls = set()
        try:
            page.wait_for_selector(".skill-card", state="attached", timeout=10000)
            page.wait_for_timeout(1000)
            skill_cards = page.query_selector_all(".skill-card")
            processed_skills = set()

            for card in skill_cards:
                # 🎯 过滤 1：彻底干掉空名字的占位卡！
                name_json = card.get_attribute("data-skill-name")
                if not name_json or '""' in name_json or name_json == "":
                    continue  # 只要没有真实名字，直接跳过

                attr = card.get_attribute("data-skill-attribute") or "attack"
                name_zh = "Unknown"
                try:
                    name_zh = json.loads(name_json).get("zh", "Unknown")
                except:
                    pass

                for img in card.query_selector_all("img"):
                    src = img.get_attribute("src") or ""
                    alt = img.get_attribute("alt") or ""

                    if "assets.merui.net/fight/skill" in src:
                        filename = src.split("/")[-1]

                        # 🎯 过滤 2：硬核拉黑所有 110x 的通用占位图
                        if filename in ["1101.webp", "1102.webp", "1103.webp", "1104.webp"]:
                            continue

                        if not alt or "Card Background" in alt:
                            continue

                        # 🎯 过滤 3：精准识别，支持特殊技能
                        if "Ultimate" in alt:
                            skill_id = "unique"
                        elif "Extra Skill" in alt:
                            skill_id = "skill4"
                        elif "Pursuit" in alt:
                            skill_id = "pursuit"  # 识别追击/特殊技能
                        else:
                            match_alt = re.search(r'Skill (\d+)', alt)
                            if match_alt:
                                skill_id = f"skill{match_alt.group(1)}"
                            else:
                                continue  # 其他无法识别的名称直接扔

                        # 🎯 过滤 4：严格去重
                        if skill_id in processed_skills:
                            break
                        processed_skills.add(skill_id)

                        is_ult = (skill_id == "unique")
                        icon_urls.add((skill_id, src))
                        skills_data.append({
                            "id": skill_id,
                            "name": name_zh,
                            "icon": f"icons/{skill_id}.webp",
                            "type": "ultimate" if is_ult else attr,
                            "sequence": [skill_id],
                            "star": 1 if not is_ult else 3
                        })
                        break
        except Exception as e:
            print(f"❌ 技能抓取失败: {e}")

        # === 2. 人工介入并智能侦测 ===
        print("\n重新回到主页...")
        page.goto(CHAR_URL_BASE, wait_until="commit", timeout=30000)
        page.wait_for_timeout(3000)
        wait_for_page_ready(page)

        print("\n⚠️ ================= 【人工操作】 =================")
        print("请在弹出的浏览器中手动完成以下操作：")
        print("1. 点击 L2D")
        print("2. 点击 Chibi 分类（或者随便点一个）")
        print("3. 随便点击一个大图进入渲染界面")
        print("👉 脚本正在后台智能侦测右上角的下拉菜单 (#l2dGarmentBtn)...")
        print("   （只要您成功进入渲染界面，脚本会自动瞬间接手，无需按回车！）")
        print("===================================================\n")

        try:
            # 智能等待：只要用户手动把下拉菜单点出来了，最多等 60 秒
            page.wait_for_selector("#l2dGarmentBtn", state="visible", timeout=90000)
            print("✅ 侦测到界面就绪！准备抓取模型。")
        except Exception:
            print("❌ 等待超时：90秒内未侦测到右上角的下拉菜单，请确保您已经点开了大图。")
            try:
                browser.close()
            except Exception as e:
                print(f"❌ 发生致命错误: {e}")
            finally:
                # 🎯 无论成功失败，强制关闭浏览器，防止后台残留僵尸进程锁死 GPU
                try:
                    context.close()
                    browser.close()
                    print("🧹 浏览器资源已彻底清理。")
                except Exception:
                    pass
            return
        page.wait_for_timeout(2500)
        print("正在自动展开下拉列表...")
        try:
            page.locator("#l2dGarmentBtn").click(timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(2000)  # 等列表渲染

        print("准备开始串行探测与下载...")

        # 🎯 核心修复：强行等待 chibi 按钮出现，防止网页卡顿导致数量为 0
        try:
            page.wait_for_selector('button[data-kind="chibi"]', state="attached", timeout=15000)
        except Exception:
            print("❌ 15秒内未找到 Chibi 皮肤按钮，请确保在网页中正确点开了角色大图！")
            garments = []
            # 直接跳过后续操作，防止越界
            return

        # 此时按钮列表在 DOM 里
        garment_buttons = page.locator('button[data-kind="chibi"]')
        count = garment_buttons.count()
        print(f"找到 {count} 个 Chibi 按钮，开始处理...")

        garments = []
        seen_ids = set()

        for i in range(count):
            btn = garment_buttons.nth(i)
            g_id = btn.get_attribute("data-garment-id")
            g_name = btn.locator("span.truncate").inner_text().strip()

            if not g_id or g_id in seen_ids: continue
            seen_ids.add(g_id)

            if g_id.endswith("01"):
                folder = f"characters/{CHAR_NAME}"
            elif g_id.endswith("02"):
                folder = f"characters/{CHAR_NAME}_insight2"
            else:
                folder = f"characters/{CHAR_NAME}_{g_id}"
            if not os.path.exists(folder): os.makedirs(folder)

            print(f"\n[{i + 1}/{count}] 探测模型: {g_name} (UI ID: {g_id})")

            current_real_model_url = None

            # 1. 🎯 核心修复：点击前，强制清空浏览器内存里的资源加载记录！
            try:
                page.evaluate("() => window.performance.clearResourceTimings()")
            except Exception:
                pass

            # 2. 尝试点击按钮
            try:
                btn.evaluate("el => el.click()")
                page.wait_for_timeout(1500)  # 多给一点时间让它响应
            except Exception as e:
                print(f"  ⚠️ 点击失败: {e}")

            # 3. 从性能面板中获取刚刚加载的真实 URL
            js_get_resources = """
                        () => {
                            let urls = [];
                            const res = window.performance.getEntriesByType("resource");
                            for (let i = 0; i < res.length; i++) {
                                if (res[i].name.includes("model.merui.net/chibi/") && res[i].name.endsWith(".skel")) {
                                    urls.push(res[i].name);
                                }
                            }
                            return urls;
                        }
                        """
            try:
                loaded_skel_urls = page.evaluate(js_get_resources)
                if loaded_skel_urls:
                    current_real_model_url = loaded_skel_urls[-1]  # 取最新的一条
                    print(f"  🎯 截获真实请求: {current_real_model_url}")
            except Exception:
                pass

            # 4. 判定真实 ID 及下载
            real_id = None
            if current_real_model_url:
                match = re.search(r'/(\d+)\.skel$', current_real_model_url)
                if match:
                    real_id = match.group(1)

            # 如果没抓到，或者发现抓到的 ID 还是刚才上一个皮肤的，就盲猜
            if not real_id:
                candidate_ids = [g_id]
                if len(g_id) == 6:
                    if g_id.startswith("3025"):
                        candidate_ids.extend(["5005" + g_id[-2:], "3005" + g_id[-2:]])
                    else:
                        candidate_ids.extend(["500" + g_id[-3:], "300" + g_id[-3:], "501" + g_id[-3:]])

                print(f"  ⚠️ 未截获真实 URL，尝试盲猜...")
                for cid in candidate_ids:
                    test_url = f"https://model.merui.net/chibi/{cid}/{cid}.skel"
                    try:
                        resp = page.request.get(test_url, timeout=3000, headers={"Range": "bytes=0-100"})
                        if resp.status == 200 or resp.status == 206:
                            real_id = cid
                            print(f"  🎯 探测成功: 真实 ID 为 {real_id}")
                            break
                    except Exception:
                        pass

            if not real_id:
                print(f"  ❌ 探测彻底失败，跳过该皮肤")
                continue

            # 5. 真正的下载并检验文件合法性
            base_url = f"https://model.merui.net/chibi/{real_id}/{real_id}"
            skel_path = os.path.join(folder, f"{real_id}.skel")

            skel_ok = download_file(f"{base_url}.skel", skel_path)
            if skel_ok:
                # 校验：如果 skel 文件小于 1KB，说明下到了 404 错误页
                if os.path.getsize(skel_path) < 1024:
                    print(f"  ❌ skel 文件异常 (大小仅 {os.path.getsize(skel_path)} 字节)，可能是错误页，跳过。")
                    os.remove(skel_path)
                    continue

                # 下载图集
                atlas_path = os.path.join(folder, f"{real_id}.atlas")
                atlas_ok = download_file(f"{base_url}.atlas", atlas_path)

                # 校验：atlas 必须包含 page 文本，否则就是下到了网页
                if atlas_ok:
                    with open(atlas_path, 'r', encoding='utf-8', errors='ignore') as f:
                        atlas_content = f.read(500)
                        if "size:" not in atlas_content or "bounds:" not in atlas_content:
                            print(f"  ❌ atlas 文件内容非法 (可能被防盗链拦截)，跳过。")
                            continue
                else:
                    print(f"  ❌ atlas 下载失败，跳过。")
                    continue

                # 下载贴图
                download_file(f"{base_url}.webp", os.path.join(folder, f"{real_id}.webp"))

                # 下载头像
                if not download_file(f"https://assets.merui.net/headicon_small/{real_id}.webp",
                                     os.path.join(folder, "headicon.webp"), retries=1):
                    download_file(f"https://assets.merui.net/headicon_small/{g_id}.webp",
                                  os.path.join(folder, "headicon.webp"), retries=1)

                garments.append({"ui_id": g_id, "name": g_name, "folder": folder})
                print(f"  ✅ 模型下载完成")
            else:
                print(f"  ❌ skel 下载失败，跳过")

            # 真正的下载
            base_url = f"https://model.merui.net/chibi/{real_id}/{real_id}"
            skel_ok = download_file(f"{base_url}.skel", os.path.join(folder, f"{real_id}.skel"))
            if skel_ok:
                print(f"  ✅ 模型下载成功")
                download_file(f"{base_url}.atlas", os.path.join(folder, f"{real_id}.atlas"))
                download_file(f"{base_url}.webp", os.path.join(folder, f"{real_id}.webp"))

                if not download_file(f"https://assets.merui.net/headicon_small/{real_id}.webp",
                                     os.path.join(folder, "headicon.webp"), retries=1):
                    download_file(f"https://assets.merui.net/headicon_small/{g_id}.webp",
                                  os.path.join(folder, "headicon.webp"), retries=1)

                garments.append({"ui_id": g_id, "name": g_name, "folder": folder})

        # === 3. 分发技能图标 ===
        first_icon_dir = os.path.join(garments[0]["folder"], "icons") if garments else ""
        if first_icon_dir:
            if not os.path.exists(first_icon_dir): os.makedirs(first_icon_dir)

            def download_icon_with_retry(sid, url):
                save_path = os.path.join(first_icon_dir, f"{sid}.webp")
                if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    return True

                # 🎯 核心修复：给技能图标单独拉满 3 次重试，超时放宽到 15 秒
                for attempt in range(3):
                    try:
                        resp = requests.get(url, stream=True, timeout=15, headers=HEADERS, verify=False)
                        if resp.status_code == 200:
                            with open(save_path, 'wb') as f:
                                for chunk in resp.iter_content(chunk_size=8192): f.write(chunk)
                            print(f"  ✅ 技能图标下载成功: {sid}.webp")
                            return True
                        else:
                            print(f"  ⚠️ 尝试 {attempt + 1} 失败 (状态码: {resp.status_code}): {sid}")
                    except Exception as e:
                        print(f"  ⚠️ 尝试 {attempt + 1} 网络异常: {sid} ({e})")
                    time.sleep(1)  # 歇 1 秒再重试

                print(f"  ❌ 彻底放弃下载图标: {sid}")
                return False

            print(f"正在下载 {len(icon_urls)} 个技能图标...")
            # 使用线程池并发下载，速度拉满
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 提交所有任务
                futures = [executor.submit(download_icon_with_retry, sid, url) for sid, url in icon_urls]
                # 等待全部结束
                for future in futures:
                    future.result()

            # 复制给所有其他皮肤
            for g in garments:
                folder = g["folder"]
                if folder != garments[0]["folder"]:
                    src_icons = os.path.join(garments[0]["folder"], "icons")
                    dst_icons = os.path.join(folder, "icons")
                    if os.path.exists(dst_icons): shutil.rmtree(dst_icons)
                    if os.path.exists(src_icons): shutil.copytree(src_icons, dst_icons)

        # === 4. 抓取语音（分批处理，防止污染） ===
        print("\n开始抓取语音...")
        voice_url = f"{CHAR_URL_BASE.split('?')[0]}?page=info&tab=voice"
        page.goto(voice_url, wait_until="commit", timeout=300000)
        page.wait_for_timeout(4000)
        wait_for_page_ready(page)

        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="spider_sounds_")

        # --- 4.1 抓默认语音 ---
        print(">> 抓取默认语音 (Default)...")
        default_sounds_dir = os.path.join(temp_dir, "default")
        os.makedirs(default_sounds_dir, exist_ok=True)

        # 👈 接收默认字幕字典
        default_action_sounds, default_idle_chats, def_tasks, default_subtitles = fetch_voices_from_current_page(page,
                                                                                                                 default_sounds_dir)

        if def_tasks:
            print(f"  正在并发下载 {len(def_tasks)} 个默认语音...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                executor.map(lambda x: download_file(x[0], x[1]), def_tasks)

        # --- 4.2 抓专属语音并立刻分发 ---
        for g in garments:
            if g["name"] == "Default": continue

            tab_locator = page.locator(".voice-garment-tab").filter(has_text=g["name"])
            if tab_locator.count() > 0 and tab_locator.first.is_visible():
                print(f"\n>> 发现专属语音页签: {g['name']}，正在切换...")
                tab_locator.first.click()
                page.wait_for_timeout(2000)

                custom_sounds_dir = os.path.join(temp_dir, f"custom_{g['ui_id']}")
                os.makedirs(custom_sounds_dir, exist_ok=True)

                # 👈 接收专属字幕字典 g_subs
                g_action, g_idle, g_tasks, g_subs = fetch_voices_from_current_page(page, custom_sounds_dir)

                if g_tasks:
                    print(f"  正在并发下载 {len(g_tasks)} 个专属语音...")
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        executor.map(lambda x: download_file(x[0], x[1]), g_tasks)

                    folder = g["folder"]
                    dst_sounds = os.path.join(folder, "sounds")
                    if os.path.exists(dst_sounds): shutil.rmtree(dst_sounds)
                    shutil.copytree(custom_sounds_dir, dst_sounds)

                    g["custom_action"] = g_action
                    g["custom_idle"] = g_idle
                    g["custom_subtitles"] = g_subs
                    g["has_custom_voice"] = True

                    # 🎯 核心修复：如果专属语音里没有闲聊，自动补充默认闲聊
                    if not g_idle:
                        print(f"  💡 发现该皮肤只有战斗语音，正在补充默认闲聊语音及字幕...")
                        # 1. 物理复制默认闲聊音频文件到该皮肤的 sounds 目录
                        for time_key, files in default_idle_chats.items():
                            for f in files:
                                src_file = os.path.join(default_sounds_dir, f)
                                dst_file = os.path.join(dst_sounds, f)
                                if os.path.exists(src_file):
                                    shutil.copy(src_file, dst_file)

                        # 2. 在内存中合并默认闲聊配置和字幕
                        g["custom_idle"] = default_idle_chats
                        for k, v in default_subtitles.items():
                            # 只要这个字幕对应的音频名在默认闲聊列表里，就合并进去
                            if any(k in idle_list for idle_list in default_idle_chats.values()):
                                g["custom_subtitles"][k] = v
                else:
                    print(f"  ⚠️ 未发现有效专属语音，将使用默认语音")
                    g["has_custom_voice"] = False

                shutil.rmtree(custom_sounds_dir)
            else:
                g["has_custom_voice"] = False

        try:
            browser.close()
        except Exception as e:
            print(f"❌ 发生致命错误: {e}")
        finally:
            try:
                context.close()
                browser.close()
                print("🧹 浏览器资源已彻底清理。")
            except Exception:
                pass

    # === 5. 统一分发默认语音并生成配置 ===
    print("\n开始分发默认语音及生成配置...")
    for g in garments:
        folder = g["folder"]
        dst_sounds = os.path.join(folder, "sounds")

        if not g.get("has_custom_voice", False):
            # 没有专属语音，分发默认音频和默认字幕
            if os.path.exists(dst_sounds): shutil.rmtree(dst_sounds)
            shutil.copytree(default_sounds_dir, dst_sounds)
            final_actions = default_action_sounds
            final_idles = default_idle_chats
            final_subtitles = default_subtitles  # 👈 使用默认字幕
        else:
            # 有专属语音，使用专属音频和专属字幕
            final_actions = g["custom_action"]
            final_idles = g["custom_idle"]
            final_subtitles = g["custom_subtitles"]  # 👈 使用专属字幕

        # 写 config.json
        with open(os.path.join(folder, "config.json"), 'w', encoding='utf-8') as f:
            json.dump({"scale": 1.00, "skills": skills_data, "action_sounds": final_actions, "idle_chats": final_idles},
                      f, indent=4, ensure_ascii=False)

        # 写 subtitles.json
        with open(os.path.join(folder, "subtitles.json"), 'w', encoding='utf-8') as f:
            json.dump(final_subtitles, f, indent=4, ensure_ascii=False)

    # 清理总临时文件夹
    shutil.rmtree(temp_dir)
    print(f"\n🎉 抓取全部完成！共生成/更新了 {len(garments)//2} 个皮肤文件夹。")

if __name__ == "__main__":
    main()