## 실행 : uvicorn simple_fastapi_auth:app --reload

from fastapi import FastAPI, HTTPException
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# FastAPI 애플리케이션 생성
app = FastAPI(title="PNU Scholarship Parser API")

# 인메모리 저장소: parsed_docs[id] = {"title": ..., "content_html": ...}
parsed_docs = {}
next_id = 1  # 문서 ID 부여용

# 환경 변수 또는 설정 파일에서 Upstage API 키 불러오기
UPSTAGE_API_KEY = "YOUR_API_KEY_HERE"  # 실제 키로 교체하거나 환경변수 사용

# [보조 함수] 장학공지 게시판 크롤링 및 파싱 함수
import requests
from bs4 import BeautifulSoup

# [중략: FastAPI, imports, etc.]

def crawl_and_parse():
    global next_id
    base_url = "https://cse.pusan.ac.kr"
    list_url = f"{base_url}/bbs/cse/2605/artclList.do"
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()

    print("[START] 크롤링 시작")
    resp = session.get(list_url, headers=headers)
    print(f"[DEBUG] 목록 페이지 status: {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = soup.select("td._artclTdTitle a.artclLinkView")
    print(f"[INFO] 게시글 수: {len(articles)}")

    for a in articles:
        try:
            title = a.get_text(strip=True)
            detail_url = urljoin(base_url, a["href"])
            print(f"[INFO] 처리 중: {title}")

            # 상세 페이지
            detail_resp = session.get(detail_url, headers=headers)
            detail_resp.raise_for_status()
            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

            # ⬇ 첨부파일 링크 (.pdf·.hwp 등) ― href에 /download.do 포함
            file_links = detail_soup.select(
                'dl.artclForm dd.artclInsert li a[href*="/download.do"]'
            )
            print(f"[DEBUG] 첨부파일 수: {len(file_links)}")
            if not file_links:
                continue  # 첨부파일 없으면 건너뜀

            # 첫 번째 첨부파일만 처리 (필요하면 for file_link in file_links 반복)
            file_link = file_links[0]
            file_name = file_link.get_text(strip=True)
            file_url = urljoin(detail_url, file_link["href"])

            # 파일 다운로드
            file_resp = session.get(file_url, headers=headers)
            file_resp.raise_for_status()
            file_content = file_resp.content

            # Upstage Document Parser
            api_url = "https://api.upstage.ai/v1/document-ai/document-parse"
            api_headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}"}
            files = {"document": file_content}
            api_resp = requests.post(api_url, headers=api_headers, files=files)
            api_resp.raise_for_status()
            result_json = api_resp.json()

            # HTML 추출
            elements = result_json.get("elements", [])
            html_segments = [
                elem["content"].get("html", "") for elem in elements if "content" in elem
            ]
            full_html = "\n".join(html_segments)

            # 메모리 저장
            parsed_docs[next_id] = {
                "title": f"{title} ({file_name})" if file_name else title,
                "content_html": full_html,
            }
            print(f"[✅ 저장됨] ID {next_id} - {title}")
            next_id += 1

        except Exception as e:
            print(f"[ERROR] {title} 처리 중 오류 발생: {e}")




# API 엔드포인트 구현

@app.get("/scholarships")
def list_scholarships():
    """저장된 모든 장학 공지 문서 목록 반환"""
    result = []
    for doc_id, doc in parsed_docs.items():
        result.append({"id": doc_id, "title": doc["title"]})
    return result

@app.get("/scholarships/{doc_id}")
def get_scholarship(doc_id: int):
    """지정한 ID의 장학 공지 문서 내용 반환 (HTML)"""
    doc = parsed_docs.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # HTML 콘텐츠를 응답 (필요하다면 text/plain으로 변환 가능)
    return {"id": doc_id, "title": doc["title"], "content_html": doc["content_html"]}

@app.post("/scholarships/refresh")
def refresh_scholarships():
    """장학 공지사항 게시판을 크롤링하여 최신 문서 파싱 (기존 데이터 초기화)"""
    parsed_docs.clear()
    global next_id
    next_id = 1
    try:
        crawl_and_parse()
        return {"status": "success", "count": len(parsed_docs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# (옵션) 서버 시작 시 자동 크롤링 수행
# crawl_and_parse()
