# 프로젝트 이름

> 한 줄 소개

---

## 목차
- [소개](#소개)
- [팀원](#팀원)
- [기술 스택](#기술-스택)
- [주요 기능](#주요-기능)
- [실행 방법](#실행-방법)
- [폴더 구조](#폴더-구조)
- [브랜치 전략](#브랜치-전략)
- [커밋 컨벤션](#커밋-컨벤션)

---

## 소개

> 프로젝트 목적과 주요 기능을 간단히 설명해주세요.

**프로젝트 기간:** `YYYY.MM.DD - YYYY.MM.DD`

---

## 팀원

| 이름 | 역할 | GitHub |
|------|------|--------|
| 이름1 | 역할 | [@id](https://github.com/id) |
| 이름2 | 역할 | [@id](https://github.com/id) |

---

## 기술 스택

- **Frontend:**
- **Backend:**
- **Database:**
- **기타 도구:** Figma, Notion, GitHub Projects

---

## 주요 기능

- 기능 1
- 기능 2
- 기능 3

---

## 실행 방법

```bash
git clone https://github.com/yijuuuun/SWproject-Team2.git
cd SWproject-Team2

#가상환경 설치
python -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt (백엔드)
uvicorn main:app --reload --port 8000(서버 실행-> 백엔드)

# 의존성 설치
npm install

# 개발 서버 실행
npm run dev
```

---

## 폴더 구조

```
📦SWproject-Team2
┣ 📂src
┣ 📂public
┗ 📜README.md
```

---

## 브랜치 전략

- `main`: 배포 가능한 안정 버전
- `develop`: 통합 개발 브랜치
- `feature/*`: 기능 개발
- `bugfix/*`: 버그 수정

---

## 커밋 컨벤션

```
feat: 새로운 기능 추가
fix: 버그 수정
refactor: 코드 리팩토링
style: 스타일 변경
docs: 문서 수정
chore: 빌드/설정 변경
```
