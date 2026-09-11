import requests

# 1. 상수로 설정 (본인 이름과 n8n Production 웹훅 주소)
N8N_URL = "http://localhost:5678/webhook/c040e964-1a62-4382-88ac-dc793dce6df2"
STUDENT_NAME = "서효상"  # 본인 이름으로 변경하세요

# 2. 전송할 데이터 (경보 2건 이상: 거부될 레벨 10 이상, 허용될 레벨 10 미만 포함)
payload = {
    "student": STUDENT_NAME,
    "alerts": [
        {"ip": "1.2.3.114", "level": 10, "rule": "5712"},
        {"ip": "192.168.0.10", "level": 3, "rule": "1234"},
    ],
}

try:
  # 3. n8n 웹훅으로 POST 전송
  response = requests.post(N8N_URL, json=payload, timeout=5)
  print(f"[n8n] 전송 성공! 응답 코드: {response.status_code}")
  print(f"응답 내용: {response.text}")
except Exception as e:
  # 4. 전송 실패 시 프로그램이 죽지 않고 오류 메시지만 출력
  print(f"[오류] n8n 통신 실패: {e}")