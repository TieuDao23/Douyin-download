import streamlit as st
import re
import time
import os
import urllib.parse
import requests
from bs4 import BeautifulSoup

# --- MẸO DEPLOY CLOUD: ÉP CÀI TRÌNH DUYỆT ẢO --- 
# Streamlit Cloud không tự chạy lệnh cài chromium, ta ép nó cài qua OS command trong lần chạy đầu tiên
if not os.path.exists("/tmp/playwright_installed"):
    os.system("playwright install chromium")
    os.system("touch /tmp/playwright_installed")

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

def clean_url(url):
    if not url: return url
    if url.startswith("//"): return "https:" + url
    if url.startswith("/"): return "https://www.douyin.com" + url
    return url

def extract_douyin_data(share_text):
    url_match = re.search(r'https?://[a-zA-Z0-9./_?=-]*douyin\.com[a-zA-Z0-9./_?=-]*', share_text)
    if not url_match:
        return {"error": "⚠️ Không tìm thấy URL Douyin hợp lệ trong chuỗi chia sẻ."}
    raw_url = url_match.group(0).rstrip('/_.,;:"\'')

    result = {
        "type": "video",
        "desc": "Nội dung Douyin",
        "author": "Unknown",
        "video_url": None,
        "music_url": None,
        "music_title": "Audio Gốc",
        "images": [],
        "stats": {}
    }

    # ==========================================
    # BƯỚC 1: SỬ DỤNG PLAYWRIGHT ĐỂ BẮT LUỒNG MẠNG VÀ CÀO DỮ LIỆU GỐC (ƯU TIÊN 1)
    # ==========================================
    if HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
                    viewport={"width": 375, "height": 812},
                    is_mobile=True
                )
                page = context.new_page()
                
                def handle_response(response):
                    try:
                        url = response.url
                        content_type = response.headers.get('content-type', '')
                        if "v26-web.douyinvod.com" in url or "video/tos" in url or "aweme/v1/play" in url:
                            if (".mp4" in url or "play" in url) and not result["video_url"]:
                                result["video_url"] = clean_url(url.replace("playwm", "play"))
                        if ("douyinpic.com" in url or "p3-sign.douyinpic.com" in url or "p9-pc.douyinpic.com" in url):
                            if "image" in content_type and "100x100" not in url and "avatar" not in url:
                                 clean_img = clean_url(url)
                                 if clean_img not in result["images"]:
                                      result["images"].append(clean_img)
                        if (".mp3" in url or "audio/" in content_type) and "v26-web.douyinvod.com" not in url:
                            if not result["music_url"]:
                                result["music_url"] = clean_url(url)
                    except: pass

                page.on("response", handle_response)
                page.goto(raw_url, wait_until="networkidle", timeout=20000)
                
                try:
                    title = page.evaluate("() => document.title")
                    if "-" in title: result["desc"] = title.split("-")[0].strip()
                    else: result["desc"] = title
                except: pass
                
                # Trích xuất JSON nội bộ để dọn rác và phân loại chuẩn xác
                try:
                    final_url = page.url
                    match = re.search(r'(video|note)/(\d+)', final_url)
                    current_id = match.group(2) if match else ""
                    
                    state_data = page.evaluate("() => window._ROUTER_DATA || window.SSR_DATA || window._SSR_DATA || {}")
                    import json
                    def find_current_aweme(data, target_id):
                        if isinstance(data, dict):
                            if data.get("aweme_id") == target_id: return data
                            for key, value in data.items():
                                res = find_current_aweme(value, target_id)
                                if res: return res
                        elif isinstance(data, list):
                            for item in data:
                                res = find_current_aweme(item, target_id)
                                if res: return res
                        return None

                    if state_data and current_id:
                        aweme = find_current_aweme(state_data, current_id)
                        if aweme:
                            result["author"] = aweme.get("author", {}).get("nickname", result["author"])
                            result["desc"] = aweme.get("desc", result["desc"])
                            if "images" in aweme and aweme["images"]:
                                clean_images = []
                                for img in aweme["images"]:
                                    if isinstance(img, dict) and "url_list" in img and img["url_list"]:
                                        clean_images.append(clean_url(img["url_list"][0]))
                                if clean_images:
                                    result["images"] = clean_images
                                    result["type"] = "images"
                                    result["video_url"] = None
                            elif "video" in aweme:
                                result["type"] = "video"
                                result["images"] = []
                            if "music" in aweme and aweme["music"].get("play_url") and aweme["music"]["play_url"].get("url_list"):
                                result["music_url"] = clean_url(aweme["music"]["play_url"]["url_list"][0])
                                result["music_title"] = aweme["music"].get("title", "Audio Gốc")
                except:
                    pass
                    
                browser.close()
        except:
            pass
            
    # ==========================================
    # BƯỚC 2: FALLBACK BẰNG CLOUD API 
    # (Chỉ kích hoạt nếu Playwright gặp sự cố trên máy chủ Linux)
    # ==========================================
    # Giải mã ID
    headers_mobile = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15'}
    video_id = None
    try:
        response = requests.get(raw_url, headers=headers_mobile, allow_redirects=True, timeout=10)
        final_url = response.url
        match = re.search(r'(video|note)/(\d+)', final_url)
        if match:
            video_id = match.group(2)
        else:
            match = re.search(r'aweme_id=(\d+)', final_url)
            if match:
                video_id = match.group(1)
        if not video_id:
            match = re.search(r'\d{19,}', raw_url)
            if match: video_id = match.group(0)
    except:
        pass
        
    if video_id:
        try:
            panda_url = f"https://dlpanda.com/vi/douyin?url=https://www.douyin.com/video/{video_id}&token=G7eRpMaa"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
            panda_res = requests.get(panda_url, headers=headers, timeout=15)
            soup = BeautifulSoup(panda_res.text, 'html.parser')
            
            title_tag = soup.find('h5')
            if title_tag and title_tag.text:
                result["desc"] = title_tag.text.strip()
                
            audio_tag = soup.find('audio')
            if audio_tag and audio_tag.get('src'):
                result["music_url"] = clean_url(audio_tag['src'])
                result["music_title"] = "Bản thu âm gốc Douyin"
                
            video_tag = soup.find('video')
            if video_tag and video_tag.get('src'):
                result["type"] = "video"
                result["video_url"] = clean_url(video_tag['src'])
            else:
                 gallery_links = soup.find_all('a', attrs={'data-fancybox': 'gallery'})
                 if gallery_links:
                     result["type"] = "images"
                     for a_tag in gallery_links:
                         img_src = a_tag.get('href')
                         if img_src and clean_url(img_src) not in result["images"]:
                             result["images"].append(clean_url(img_src))
                 else:
                     imgs = soup.find_all('img', class_='img-fluid')
                     for img in imgs:
                         src = img.get('src') or img.get('data-src')
                         if src and "avatar" not in src and "logo" not in src:
                             if clean_url(src) not in result["images"]:
                                  result["images"].append(clean_url(src))
                     if len(result["images"]) > 0:
                          result["type"] = "images"
        except:
            pass
            
        if not result["video_url"] and len(result["images"]) == 0:
            try:
                api_res = requests.post("https://www.tikwm.com/api/", data={"url": f"https://www.douyin.com/video/{video_id}", "hd": 1}, timeout=10)
                api_data = api_res.json()
                if api_data.get("code") == 0:
                    vd = api_data.get("data", {})
                    result["author"] = vd.get("author", {}).get("nickname", "Unknown")
                    if result["desc"] == "Nội dung Douyin": result["desc"] = vd.get("title", "")
                    
                    if vd.get("images"):
                        result["type"] = "images"
                        result["images"] = [clean_url(img) for img in vd.get("images")]
                    elif vd.get("hdplay"):
                        result["type"] = "video"
                        result["video_url"] = clean_url(vd.get("hdplay"))
                        
                    if not result["music_url"] and vd.get("music"):
                        result["music_url"] = clean_url(vd.get("music"))
            except:
                pass
                
    # Mã xử lý Fallback kết thúc tại đây.

    if result["video_url"] or len(result["images"]) > 0:
        if result["type"] == "images":
            result["images"] = list(set(result["images"]))
        return result
    else:
        return {"error": "🚫 Không thể lấy dữ liệu. Hãy thử lại hoặc bài đăng bị giới hạn khu vực."}

# --- GIAO DIỆN STREAMLIT (TÍCH HỢP RESPONSIVE MOBILE) ---
st.set_page_config(page_title="Douyin Pro Manager", page_icon="🧊", layout="centered")

# CSS Responsive & Mobile UI (Nút bấm bự, bo góc, bóng đổ)
st.markdown("""
<style>
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }
    }
    /* Tuỳ chỉnh tab điện thoại */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 45px;
        white-space: pre-wrap;
        border-radius: 8px 8px 0px 0px;
        padding-left: 10px;
        padding-right: 10px;
    }
    /* Hộp chứa Profile Info */
    .profile-box {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)

st.title("🧊 Douyin Pro Manager")
st.markdown("*(Thuật toán cốt lõi: Hybrid Cloud API. 100% Sẵn sàng Deploy Online)*")

share_text = st.text_input("🔗 Dán link chia sẻ vào đây:", placeholder="Ví dụ: https://v.douyin.com/iK5ZdlxmN_M/")

if st.button("🚀 Trích Xuất Dữ Liệu"):
    if not share_text:
        st.warning("⚠️ Vui lòng dán văn bản!")
    else:
        with st.spinner("Đang truy cập siêu tốc vào luồng dữ liệu... (Chờ 3-10s)..."):
            info = extract_douyin_data(share_text)
            
            if "error" in info:
                st.error(info["error"])
            else:
                st.success("✅ Trích xuất thành công toàn bộ Nội dung và Âm thanh!")
                
                # Hiển thị thông tin (Dạng Mobile Friendly Box)
                st.markdown(f"""
                <div class="profile-box">
                    <p style="margin:0;font-size:14px;color:#555;">👤 <b>{info['author']}</b></p>
                    <p style="margin:5px 0 0 0;font-size:15px;line-height:1.4;">📝 {info['desc']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                st.write("")
                
                tab1, tab2 = st.tabs(["🎬 Nội Dung Chính", "🎵 Nhạc MP3"])
                
                with tab1:
                    if info["type"] == "video" and info["video_url"]:
                        try:
                            st.video(info["video_url"])
                        except:
                            st.info("Trình phát không hỗ trợ dạng Video này.")
                            
                        st.markdown(f"""
                        <a href="{info['video_url']}" target="_blank" style="
                            display: block; width: 100%; text-align: center; background-color: #ff4b4b;
                            color: white; padding: 14px; border-radius: 10px; text-decoration: none;
                            font-weight: bold; font-size: 16px; margin-top: 15px; box-shadow: 0 4px 6px rgba(255, 75, 75, 0.3);
                            transition: 0.2s;
                        ">📥 TẢI VIDEO XUỐNG MÁY</a>
                        """, unsafe_allow_html=True)
                        
                    elif info["type"] == "images" and info["images"]:
                        st.info(f"Phát hiện dạng bài đăng Bộ sưu tập ({len(info['images'])} ảnh gốc)")
                        cols = st.columns(2)
                        for idx, img_url in enumerate(info["images"]):
                            with cols[idx % 2]:
                                st.image(img_url, use_container_width=True)
                                
                                st.markdown(f"""
                                <a href="{img_url}" target="_blank" style="
                                    display: block; width: 100%; text-align: center; background-color: #2196F3;
                                    color: white; padding: 10px; border-radius: 8px; text-decoration: none;
                                    font-weight: bold; font-size: 15px; margin-bottom: 20px;
                                    box-shadow: 0 2px 4px rgba(33, 150, 243, 0.3);
                                ">📥 TẢI ẢNH {idx+1}</a>
                                """, unsafe_allow_html=True)
                                
                with tab2:
                    if info.get("music_url"):
                        st.markdown(f"**Bài hát:** {info['music_title']}")
                        try:
                            st.audio(info["music_url"])
                        except:
                            st.warning("Trình phát ẩn không hỗ trợ dạng audio trực tuyến này.")
                            
                        st.markdown(f"""
                        <a href="{info['music_url']}" target="_blank" style="
                            display: block; width: 100%; text-align: center; background-color: #00cc66;
                            color: white; padding: 14px; border-radius: 10px; text-decoration: none;
                            font-weight: bold; font-size: 16px; margin-top: 15px; box-shadow: 0 4px 6px rgba(0, 204, 102, 0.3);
                        ">🎵 TẢI NHẠC MP3 TRỰC TUYẾN</a>
                        """, unsafe_allow_html=True)
                    else:
                        st.info("Video này được lồng ghép âm thanh kín, không có tệp nhạc rời.")
                        st.markdown(f"👉 Nếu bạn muốn lấy âm thanh của bài đăng này, hãy **Tải Video Xuống Máy** rồi sử dụng các công cụ chuyển đổi mp4 sang mp3.")
