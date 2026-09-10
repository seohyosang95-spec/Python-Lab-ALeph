# 등급 기반 접근 제어 (오전 미니 실습)

카페 회원 등급에 빗대어 게시판 사용자를 세 등급으로 나누고, 등급별로 페이지
접근을 막는 실습이다. 목적은 **접근 제어가 실제로 동작하는지 확인**하는 것이다.

| 등급 | 값 | 설명 | 접근 가능 |
|---|---|---|---|
| 일반 | `0` | 최초 가입 상태 | `/`, `/public-posts` |
| 골드 | `1` | 중간 관리자 | 위 + `/gold` |
| 관리자 | `2` | 전체 관리 | 위 + `/admin` |

등급은 **숫자가 클수록 권한이 넓다**. 그래서 검사는 `user.role >= 요구등급`
한 줄로 끝나고, 관리자는 골드 페이지도 자동으로 볼 수 있다.

---

## 1. 설계에서 정한 것

### 인가는 서버에서 한다

원래 이 프로젝트는 JWT 를 `localStorage` 에 두고 JS 가 `Authorization` 헤더로
보내는 구조였다. 이대로면 페이지 접근 제어를 JS 로밖에 못 하는데, 그건
**링크를 숨기는 것**일 뿐 주소창에 `/admin` 을 직접 치면 그대로 열린다.
접근 제어가 아니다.

그래서 로그인할 때 JWT 를 **쿠키로도 발급**한다. 주소창 이동(GET)에도 토큰이
실리므로, 서버가 페이지를 그리기 전에 등급을 확인하고 거절할 수 있다.

```
로그인 → JWT 발급 → ① 응답 본문 (localStorage용, 기존 fetch 가 사용)
                  → ② Set-Cookie (페이지 이동 시 서버가 등급 판정)
```

기존 API 호출은 헤더 방식 그대로라 아무것도 깨지지 않는다.

### CSRF 보호는 켜 둔다

쿠키 인증을 붙이면 CSRF 가 따라온다. `JWT_COOKIE_CSRF_PROTECT = True` 로 두었다.

- 페이지 라우트는 GET 이라 CSRF 검사 대상이 아니다 → 영향 없음
- 변경 API 는 헤더 토큰을 쓴다 → 영향 없음
- 화면 JS 는 `authHeaders()` 로 헤더 토큰과 `X-CSRF-TOKEN` 을 함께 보낸다

### 화면 표시와 인가 판정의 출처를 하나로 맞춘다

헤더의 유저명·등급 배지는 `localStorage` 가 아니라 **서버가 렌더링**한다.
화면에 보이는 등급과 실제로 접근을 판정하는 값이 둘 다 DB 의 `users.role` 에서
나오므로 "화면엔 골드인데 실제론 막힌다" 같은 어긋남이 생기지 않는다.

### 접속 정보를 .env 로 뺐다

`app.py` 에 DB 비밀번호가 그대로 적혀 있었다. `os.environ.get(...)` 로 바꾸되
**기본값은 원래 값 그대로**라, `.env` 가 없는 PC 에서는 동작이 달라지지 않는다.

### DB 를 이 실습 전용으로 분리했다

원래 접속 대상이 `my_new_board_db` 였는데, 이 이름은 다른 실습에서도 쓰는
스키마다. 그대로 두면 두 과제의 `users`·`posts` 가 같은 테이블을 공유해
데이터가 섞이고, 제출 증거의 회원 목록에 남의 과제 계정이 끼어든다.

그래서 `docker-compose.yml` 로 **이 실습만의 MySQL** 을 띄운다. 컨테이너·
볼륨·호스트 포트·스키마가 전부 전용이라 서로를 건드리지 않는다.
호스트 포트를 3307 로 둔 것도 같은 이유다 — 3306 은 다른 실습이 이미 쓰고 있다.

---

## 2. 구현 구조

기존처럼 `app.py` 한 파일에 모아 두었다. 추가된 덩어리는 네 개다.

```
app.py
  ├─ 등급 정의            ROLE_USER / ROLE_GOLD / ROLE_ADMIN, role_name()
  ├─ User.role 컬럼       기본값 0, has_role(), to_dict()
  ├─ 인가(권한 검사)      current_user(), api_role_required(), page_role_required()
  └─ 라우트               /gold, /admin, /api/admin/users, /api/auth/me, logout

templates/
  _nav.html      등급 링크 + 유저명·권한 표기 (모든 페이지 공용)
  gold.html      골드 전용 화면
  admin.html     관리자 회원 관리 화면
  403.html       접근 거부 예외 화면
  index.html     헤더를 _nav.html 로 교체

manage_roles.py            role 컬럼 추가 / 등급 지정 CLI
role_evidence.sql          DB 증거용 조회
capture_role_evidence.py   제출 화면 15장 자동 캡처
tests/test_authz.py        접근 제어 테스트 31개
tests/conftest.py          테스트는 항상 메모리 sqlite 를 쓰도록 고정
```

### 인가 검사 한 곳

```python
def api_role_required(required_role):   # JSON API 용  → 401/403 JSON
def page_role_required(required_role):  # 페이지 용    → 401/403 예외 화면
```

두 데코레이터는 같은 판정을 쓰고 응답 형식만 다르다.

- **로그인 안 됨 → 401** (인증 실패)
- **로그인은 됐지만 등급 부족 → 403** (인가 실패)

둘을 섞지 않은 이유는 화면에서 원인을 바로 구분하기 위해서다. 401 은
"로그인하세요", 403 은 "등급이 모자랍니다" 로 안내가 달라진다.

### 라우트에 붙이는 법

```python
@app.route('/gold')
@page_role_required(ROLE_GOLD)     # 골드(1) 이상
def gold_lounge(): ...

@app.route('/admin')
@page_role_required(ROLE_ADMIN)    # 관리자(2)만
def admin_console(): ...

@app.route('/api/admin/users', methods=['GET'])
@api_role_required(ROLE_ADMIN)
def list_users(): ...
```

---

## 3. API

| 메서드 | 경로 | 요구 등급 | 설명 |
|---|---|---|---|
| POST | `/api/auth/register` | - | 가입. **항상 일반(0)**, 본문의 `role` 은 무시 |
| POST | `/api/auth/login` | - | 로그인. 토큰 + 쿠키 발급, 등급 반환 |
| POST | `/api/auth/logout` | - | 쿠키 삭제 |
| GET | `/api/auth/me` | - | 현재 로그인 상태와 등급 |
| GET | `/api/admin/users` | 관리자 | 회원 목록(등급·게시글 수) |
| PATCH | `/api/admin/users/<id>` | 관리자 | 등급 수정 |
| DELETE | `/api/admin/users/<id>` | 관리자 | 회원 삭제(게시글 함께 삭제) |
| PUT | `/api/posts/<id>` | 작성자 본인 | 게시글 수정 (관리자도 남의 글은 못 고침) |
| DELETE | `/api/posts/<id>` | 작성자 본인 **또는 관리자** | 게시글 삭제 |

### 안전장치

관리자가 관리 화면에서 잠기는 사고를 막는다.

- 자기 자신의 등급을 내릴 수 없다
- 자기 자신을 삭제할 수 없다
- 마지막 남은 관리자는 강등·삭제할 수 없다
- `role` 값이 0/1/2 가 아니면 400

### 게시글 삭제 권한 (+α)

관리자에게는 **삭제만** 열어 주고 수정은 열지 않았다. 부적절한 글을 내리는
것과 남의 글 내용을 바꾸는 것은 성격이 다르기 때문이다. 후자는 작성자 몰래
발언을 바꾸는 셈이라 중재 권한의 범위를 넘는다고 봤다.

관리자가 남의 글을 지우면 응답에 `moderated: true` 가 실리고, 화면에도
「관리자 권한으로 ○○님의 글을 삭제했습니다」라고 알려 준다. 목록에서도
일반 `삭제` 가 아니라 테두리가 있는 **`관리자 삭제`** 버튼으로 표시된다.

---

## 4. 실행 방법

### 이 실습은 전용 DB 를 쓴다

`docker-compose.yml` 이 이 실습만의 MySQL 을 띄운다. 컨테이너·볼륨·포트가
모두 전용이라 다른 실습 DB 를 건드리지 않는다.

| 항목 | 값 | 이유 |
|---|---|---|
| 컨테이너 | `shs95_board_mysql` | 이름 충돌 방지 |
| 볼륨 | `shs95_mysql_data` | 데이터가 섞이지 않게 |
| 호스트 포트 | **3307** | 다른 실습이 3306 을 쓰고 있어도 겹치지 않게 |
| 스키마 | `shs95_board_db` | 전용 |

### 처음 한 번

`.env.example` 을 `.env` 로 복사해 값을 채운다. (`.env` 는 커밋되지 않는다)
`docker-compose.yml` 과 `app.py` 가 **같은 `.env`** 를 읽으므로,
`MYSQL_ROOT_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_HOST_PORT` 와
`DATABASE_URL` 이 서로 어긋나면 연결되지 않는다.

```bash
docker compose up -d      # DB 시작
docker compose ps         # STATUS 가 healthy 가 될 때까지 기다린다
```

테이블은 `app.py` 를 실행하면 `db.create_all()` 이 만들어 준다.

이미 쓰던 기존 DB 를 그대로 붙이는 경우에는 `users` 테이블에 `role` 컬럼이
없다. `db.create_all()` 은 이미 있는 테이블에 컬럼을 추가하지 못하므로
**한 번만** 아래를 실행한다. (새 스키마로 시작했다면 필요 없다.)

```bash
python manage_roles.py --ensure-column
```

### 도커 명령 정리

```bash
docker compose up -d       # 시작
docker compose ps          # 상태 확인
docker compose logs -f     # 로그
docker compose down        # 정지 (데이터는 볼륨에 남는다)
docker compose down -v     # 데이터까지 삭제
```

### 계정과 등급

```bash
python manage_roles.py --promote gold01 --role 1
python manage_roles.py --promote admin01 --role 2
python manage_roles.py --list
```

### 서버

```bash
python app.py
```

---

## 5. 제출 증거

### 자동 캡처

```bash
pip install playwright
python -m playwright install chromium
python capture_role_evidence.py
```

`images/role-access/` 에 PNG 15장이 생긴다. 1440x900 뷰포트에 2배 스케일이다.
데모 계정을 심고 → 촬영하고 → 원상복구까지 자동이라 몇 번을 돌려도 같은
결과가 나온다.

| # | 파일 | 확인 포인트 |
|---|---|---|
| 01 | `anonymous-board` | 비로그인 — 등급 링크 없음 |
| 02 | `anonymous-admin-401` | **401** 로그인이 필요합니다 |
| 03 | `normal-board-header` | 헤더 **`normal01님` `일반 (0)`** |
| 04 | `normal-gold-403` | **403** 요구 골드(1) / 내 등급 일반(0) |
| 05 | `normal-admin-403` | **403** 요구 관리자(2) / 내 등급 일반(0) |
| 06 | `gold-board-header` | 헤더 **`골드 (1)`** + ☕ 골드 라운지 |
| 07 | `gold-lounge` | 골드 라운지 정상 |
| 08 | `gold-admin-403` | **403** 요구 관리자(2) / 내 등급 골드(1) |
| 09 | `admin-board-header` | 헤더 **`관리자 (2)`** + 링크 2개 + 관리자 삭제 버튼 |
| 10 | `admin-gold-allowed` | 관리자는 골드 페이지도 열림 |
| 11 | `admin-console` | 회원 목록·등급·게시글 수 |
| 12 | `admin-role-changed` | 등급 변경 성공 안내문 |
| 13 | `normal-promoted-gold-allowed` | 승급 후 403 이던 `/gold` 가 열림 |
| 14 | `admin-self-demote-blocked` | 「자기 자신의 등급은 내릴 수 없습니다」 |
| 15 | `admin-post-deleted` | 관리자가 남의 글 삭제한 결과 |

**가장 중요한 두 장은 04·05 다.** 헤더에 골드·관리자 링크가 **없는 상태에서**
주소를 직접 입력했는데도 막히는 화면이라, "링크를 숨긴 게 아니라 서버가
막는다"를 보여 준다. 예외 화면에 요구 등급과 내 등급이 나란히 찍혀서 차단
이유까지 한 장에 담긴다.

### DB 증거

`role_evidence.sql` 을 MySQL 에서 실행한다. 두 장이면 충분하다.

1. **① 회원별 등급** — 누가 어떤 등급인지
2. **③ `SHOW COLUMNS FROM users`** — `role int NO 0`,
   즉 등급이 스키마에 실재하고 **기본값이 0** 이라는 것

터미널로도 같은 내용을 볼 수 있다.

```bash
python manage_roles.py --list
```

---

## 6. 테스트

```bash
python -m pytest tests -q
```

`tests/test_authz.py` 가 접근 제어를 검증한다.

- 가입은 항상 일반(0)이고, 본문에 `role: 2` 를 넣어도 무시된다
- 비로그인/일반/골드/관리자별로 `/gold`, `/admin` 응답이 401·403·200 으로 갈린다
- 헤더에 유저명과 등급이 함께 렌더링된다
- 링크가 숨겨져도 URL 직접 입력은 서버가 막는다
- 승급 전 403 → 승급 후 200 으로 바뀐다
- 관리자 안전장치(자기 강등·자기 삭제·잘못된 role 값)가 모두 거절된다
- 관리자는 남의 글을 삭제할 수 있고, 일반·골드는 403 으로 거절된다
- 관리자도 남의 글 **수정** 은 403 으로 거절된다
- 로그아웃하면 페이지 접근이 다시 막힌다

`tests/conftest.py` 는 테스트가 **언제나 메모리 sqlite** 를 쓰도록 고정한다.
`setdefault` 가 아니라 대입인 이유는, 개발자 PC 에 `DATABASE_URL` 이 걸려
있으면 테스트가 실제 MySQL 데이터를 지워 버릴 수 있기 때문이다.

---

## 7. 작업 중 고친 것

| 문제 | 왜 문제였나 | 조치 |
|---|---|---|
| `g` 캐시가 요청을 넘어 살아남음 | `g` 는 요청이 아니라 **앱 컨텍스트**에 붙는다. 앱 컨텍스트를 하나 열어 두고 여러 요청을 보내면(테스트가 그렇다) 로그아웃한 뒤에도 이전 사용자로 인가가 통과했다 | `@app.before_request` 에서 캐시를 비움 |
| `print("… — …")` | em dash 가 cp949 콘솔에서 `UnicodeEncodeError` 로 서버가 죽었다 | 하이픈으로 교체 |
| DB 비밀번호 하드코딩 | 코드에 접속 정보가 그대로 남는다 | `.env` 로 분리(기본값은 기존 값 유지) |

---

## 8. 남는 한계 (실습 범위 밖)

- 등급 변경 이력을 남기지 않는다. 누가 언제 누구를 승급했는지 추적하려면
  별도 로그 테이블이 필요하다.
- 게시글 **수정** 은 작성자 본인만 가능하다. 관리자도 남의 글 내용은 못 고친다.
- 관리자가 지운 글은 복구할 수 없다. 실제 서비스라면 바로 지우지 말고
  `deleted_at` 을 찍어 두는 소프트 삭제가 안전하다.
- 토큰 만료(2시간) 전에 등급을 내려도 쿠키는 살아 있다. 다만 인가 판정은
  매 요청 DB 의 `users.role` 을 다시 읽으므로 **강등은 즉시 반영된다.**
