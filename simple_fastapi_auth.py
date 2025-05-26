"""
실행 예시
---------
$ uvicorn simple_fastapi_auth:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from dotenv import load_dotenv
import mimetypes
import requests
import os
import logging

# ──────────────────────────── 환경설정 ────────────────────────────
load_dotenv()                                   # .env → 환경변수 반영
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")  # 必

if not UPSTAGE_API_KEY:
    raise RuntimeError("환경변수 UPSTAGE_API_KEY 가 설정되지 않았습니다.")

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s | %(message)s")

# ──────────────────────────── FastAPI ────────────────────────────
app = FastAPI(title="PNU Scholarship Parser API")

# 인메모리 DB
parsed_docs: dict[int, dict[str, str]] = {}   # {id: {"title":.., "content_html":..}}
next_id: int = 1


# ──────────────────────────── 유틸 ────────────────────────────────
def guess_mime(fname: str) -> str:
    """
    파일 이름에서 MIME 타입 추정 (mimetypes + 확장자 보정)
    """
    mime, _ = mimetypes.guess_type(fname)
    if mime:
        return mime
    ext = Path(fname).suffix.lower()
    return {
        ".hwp":  "application/x-hwp",
        ".hwpx": "application/x-hwp",
    }.get(ext, "application/octet-stream")


def call_upstage(file_name: str, file_bytes: bytes) -> dict:
    """
    Upstage Document-Parse 동기 API 호출 후 JSON 반환
    """
    api_url = "https://api.upstage.ai/v1/document-digitization"
    headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}"}

    files = {
        "document": (file_name, file_bytes, guess_mime(file_name))
    }
    data = {
        "model": "document-parse"      # 필수
        # 필요 시 "ocr": "force", "base64_encoding": "['table']" 등 추가
    }

    resp = requests.post(api_url, headers=headers, files=files, data=data, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ──────────────────────────── 크롤러 ─────────────────────────────
def crawl_and_parse() -> None:
    """
    부산대 CSE 게시판을 돌며 첨부파일 → Upstage 변환 → HTML 저장
    """
    global next_id
    base_url = "https://cse.pusan.ac.kr"
    list_url = f"{base_url}/bbs/cse/2605/artclList.do"
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()

    logging.info("[START] 크롤링 시작")
    resp = session.get(list_url, headers=headers, timeout=15)
    logging.debug(f"[DEBUG] 목록 페이지 status: {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = soup.select("td._artclTdTitle a.artclLinkView")
    logging.info(f"[INFO] 게시글 수: {len(articles)}")

    for a in articles:
        title = a.get_text(strip=True)
        detail_url = urljoin(base_url, a["href"])
        logging.info(f"[INFO] 처리 중: {title}")

        try:
            # ── 상세 페이지 ──
            detail_resp = session.get(detail_url, headers=headers, timeout=15)
            detail_resp.raise_for_status()
            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

            file_links = detail_soup.select(
                'dl.artclForm dd.artclInsert li a[href*="/download.do"]')
            logging.debug(f"[DEBUG] 첨부파일 수: {len(file_links)}")
            if not file_links:
                continue

            file_link  = file_links[0]              # 첫 파일만
            file_name  = file_link.get_text(strip=True)
            file_url   = urljoin(detail_url, file_link["href"])

            file_resp = session.get(file_url, headers=headers, timeout=30)
            file_resp.raise_for_status()

            # ── Upstage 변환 ──
            result_json = call_upstage(file_name, file_resp.content)

            html_segments = [
                elem["content"]["html"]
                for elem in result_json.get("elements", [])
                if "content" in elem
            ]
            full_html = "\n".join(html_segments) or "<p>(빈 문서)</p>"

            parsed_docs[next_id] = {
                "title": f"{title} ({file_name})" if file_name else title,
                "content_html": full_html,
            }
            logging.info(f"[✅ 저장] ID {next_id} - {title}")
            next_id += 1

        except Exception as e:
            logging.error(f"[ERROR] {title} 처리 중 오류: {e}")


# ──────────────────────────── API 엔드포인트 ─────────────────────
@app.get("/scholarships")
def list_scholarships() -> list[dict]:
    """
    저장된 문서 목록
    """
    return [{"id": doc_id, "title": doc["title"]}
            for doc_id, doc in parsed_docs.items()]


@app.get("/scholarships/{doc_id}")
def get_scholarship(doc_id: int) -> dict:
    """
    지정 ID 문서의 HTML 반환
    """
    doc = parsed_docs.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return {"id": doc_id, "title": doc["title"], "content_html": doc["content_html"]}


@app.post("/scholarships/refresh")
def refresh_scholarships() -> dict:
    """
    게시판 재크롤링 - 메모리 초기화
    """
    parsed_docs.clear()
    global next_id
    next_id = 1
    try:
        crawl_and_parse()
        return {"status": "success", "count": len(parsed_docs)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ──────────────────────────── (옵션) 서버 기동 시 자동 수집 ─────
# crawl_and_parse()
