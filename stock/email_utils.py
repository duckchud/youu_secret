# -*- coding: utf-8 -*-
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# ==============================================================================
# 이메일 설정 (사용자 수정 필요)
# ==============================================================================
# 참고: 실제 운영에서는 보안을 위해 아래 정보들을 코드에 직접 작성하는 대신,
# 환경 변수나 별도의 설정 파일을 사용하는 것이 안전합니다.
# (예: Gmail 사용 시, '앱 비밀번호'를 생성하여 사용해야 합니다.)
# ==============================================================================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.worksmobile.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_report_email(
    recipient_email: str,
    subject: str,
    html_body: str
):
    """
    HTML 본문과 (선택적) 첨부파일을 포함한 이메일을 발송합니다.

    :param recipient_email: 받는 사람 이메일 주소
    :param subject: 이메일 제목
    :param html_body: 이메일의 HTML 본문
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print("⚠️ [이메일 발송 스킵] 이메일 설정(SMTP_USER, SMTP_PASSWORD)을 확인해주세요.")
        print("➡️ 'email_utils.py' 파일을 열어 SMTP 관련 정보를 수정해야 합니다.")
        return

    try:
        # 이메일 메시지 생성
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = recipient_email
        msg["Subject"] = subject

        # HTML 본문 추가
        msg.attach(MIMEText(html_body, "html"))

        # 이메일 서버 연결 및 발송
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # TLS 암호화
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ 이메일이 성공적으로 발송되었습니다. (수신자: {recipient_email})")

    except smtplib.SMTPAuthenticationError:
        print("❌ [이메일 발송 실패] SMTP 인증에 실패했습니다.")
        print("➡️ 'email_utils.py'의 SMTP_USER, SMTP_PASSWORD가 올바른지 확인하세요.")
        print("➡️ Gmail의 경우, 2단계 인증 사용 시 '앱 비밀번호'를 사용해야 합니다.")

    except Exception as e:
        print(f"❌ [이메일 발송 실패] 예상치 못한 오류가 발생했습니다: {e}")

