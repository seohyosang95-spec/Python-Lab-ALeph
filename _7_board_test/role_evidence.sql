-- 등급 접근 제어 · DB 증거용 조회
--
-- MySQL Shell for VS Code 등에서 이 파일을 열고 실행한다.
-- 결과 그리드를 캡처하면 "제출 항목 1 - 로그인 유저 권한, 디비" 증거가 된다.
--
-- 스키마 이름은 .env 의 DATABASE_URL 끝부분과 같아야 한다.

USE board_test_db;

-- ① 회원별 등급 (핵심 증거)
SELECT
    id                                    AS `ID`,
    username                              AS `아이디`,
    role                                  AS `권한값`,
    CASE role
        WHEN 0 THEN '일반 (최초 가입)'
        WHEN 1 THEN '골드 (중간 관리자)'
        WHEN 2 THEN '관리자'
        ELSE '알 수 없음'
    END                                   AS `등급`
FROM users
ORDER BY role DESC, id ASC;

-- ② 등급별 인원 수
SELECT
    role                                  AS `권한값`,
    CASE role
        WHEN 0 THEN '일반'
        WHEN 1 THEN '골드'
        WHEN 2 THEN '관리자'
    END                                   AS `등급`,
    COUNT(*)                              AS `인원`
FROM users
GROUP BY role
ORDER BY role DESC;

-- ③ role 컬럼이 실제로 테이블에 있는지 (기본값 0 확인)
--    "회원가입은 항상 일반(0)" 을 스키마 수준에서 보여 준다.
SHOW COLUMNS FROM users;

-- ④ 게시글과 작성자 등급 (관리자 삭제 증거용)
SELECT
    p.id                                  AS `글번호`,
    p.title                               AS `제목`,
    u.username                            AS `작성자`,
    u.role                                AS `작성자권한값`
FROM posts p
JOIN users u ON u.id = p.author_id
ORDER BY p.id DESC;
