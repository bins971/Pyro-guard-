
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import List, Optional
from datetime import datetime
import os
from ..config import settings


class AlertService:
   
    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.smtp_from = settings.SMTP_FROM
        
        # Default recipients
        self.default_recipients = settings.alert_recipients_list
    
    def send_email_alert(
        self,
        camera_name: str,
        location: str,
        fire_level: int,
        confidence: float,
        timestamp: datetime,
        image_path: Optional[str] = None,
        recipients: Optional[List[str]] = None
    ) -> bool:
        if not self.smtp_user or not self.smtp_password:
            print("Warning: SMTP credentials not configured")
            return False
        
        recipients = recipients or self.default_recipients
        if not recipients:
            print("Warning: No email recipients configured")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.smtp_from
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"🔥 FIRE ALERT - Level {fire_level} - {camera_name}"
            
            # Create email body
            level_names = {
                0: "No Fire",
                1: "Small Fire",
                2: "Medium Fire",
                3: "Large/Critical Fire"
            }
            
            level_emojis = {
                0: "✅",
                1: "⚠️",
                2: "🔶",
                3: "🚨"
            }
            
            html_body = (
                "<html>\n"
                "    <head>\n"
                "        <style>\n"
                "            body { font-family: Arial, sans-serif; }\n"
                f"            .alert-box {{\n"
                f"                border: 3px solid {'#EF4444' if fire_level >= 2 else '#FBBF24'};\n"
                f"                border-radius: 10px;\n"
                f"                padding: 20px;\n"
                f"                margin: 20px;\n"
                f"                background-color: #FEF2F2;\n"
                f"            }}\n"
                f"            .level-badge {{\n"
                f"                display: inline-block;\n"
                f"                padding: 10px 20px;\n"
                f"                border-radius: 5px;\n"
                f"                background-color: {'#EF4444' if fire_level == 3 else '#F97316' if fire_level == 2 else '#FBBF24'};\n"
                f"                color: white;\n"
                f"                font-weight: bold;\n"
                f"                font-size: 18px;\n"
                f"            }}\n"
                "            .info-table {\n"
                "                width: 100%;\n"
                "                border-collapse: collapse;\n"
                "                margin-top: 20px;\n"
                "            }\n"
                "            .info-table td {\n"
                "                padding: 10px;\n"
                "                border-bottom: 1px solid #ddd;\n"
                "            }\n"
                "            .info-table td:first-child {\n"
                "                font-weight: bold;\n"
                "                width: 150px;\n"
                "            }\n"
                "        </style>\n"
                "    </head>\n"
                "    <body>\n"
                "        <div class=\"alert-box\">\n"
                f"            <h1>{level_emojis.get(fire_level, '🔥')} FIRE DETECTION ALERT</h1>\n"
                "            <div class=\"level-badge\">\n"
                f"                Level {fire_level}: {level_names.get(fire_level, 'Unknown')}\n"
                "            </div>\n"
                "            <table class=\"info-table\">\n"
                "                <tr>\n"
                "                    <td>Camera:</td>\n"
                f"                    <td>{camera_name}</td>\n"
                "                </tr>\n"
                "                <tr>\n"
                "                    <td>Location:</td>\n"
                f"                    <td>{location or 'N/A'}</td>\n"
                "                </tr>\n"
                "                <tr>\n"
                "                    <td>Fire Level:</td>\n"
                f"                    <td>{level_names.get(fire_level, 'Unknown')}</td>\n"
                "                </tr>\n"
                "                <tr>\n"
                "                    <td>Confidence:</td>\n"
                f"                    <td>{confidence * 100:.1f}%</td>\n"
                "                </tr>\n"
                "                <tr>\n"
                "                    <td>Detected At:</td>\n"
                f"                    <td>{timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>\n"
                "                </tr>\n"
                "            </table>\n"
                "            <p style=\"margin-top: 20px; color: #DC2626; font-weight: bold;\">\n"
                "                ⚠️ Please take immediate action and verify the situation.\n"
                "            </p>\n"
                "        </div>\n"
                "    </body>\n"
                "</html>\n"
            )
            
            msg.attach(MIMEText(html_body, 'html'))
            
            # Attach image if available
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-Disposition', 'attachment', filename='detection.jpg')
                    msg.attach(img)
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            print(f"Alert email sent to {len(recipients)} recipient(s)")
            return True
            
        except Exception as e:
            print(f"Error sending email alert: {e}")
            return False

    def send_sms_alert(
        self,
        location: str,
        fire_level: int,
        timestamp: datetime,
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send fire alert via SMS using Brevo API
        """
        api_key = settings.BREVO_API_KEY
        if not api_key:
            print("Warning: Brevo API key not configured for SMS")
            return False
            
        sms_recipients_str = settings.SMS_RECIPIENTS
        recipients = recipients or [x.strip() for x in sms_recipients_str.split(',')] if sms_recipients_str else []
        if not recipients:
            print("Warning: No SMS recipients configured")
            return False
            
        import requests
        
        url = "https://api.brevo.com/v3/transactionalSMS/sms"
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json"
        }
        
        level_names = {
            0: "No Fire",
            1: "Small Fire",
            2: "Medium Fire",
            3: "Large/Critical Fire"
        }
        
        time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        content = f"🔥 FIRE DETECTED!\nLocation: {location or 'Unknown'}\nLevel: {fire_level} ({level_names.get(fire_level, 'Unknown')})\nTime: {time_str}\nPlease take immediate action!"
        
        success = False
        for recipient in recipients:
            payload = {
                "sender": "PyroGuard",
                "recipient": recipient,
                "content": content
            }
            try:
                response = requests.post(url, json=payload, headers=headers)
                if response.status_code in (200, 201, 202):
                    print(f"SMS alert sent successfully to {recipient}")
                    success = True
                else:
                    print(f"Failed to send SMS to {recipient}: {response.text}")
            except Exception as e:
                print(f"Error sending SMS alert to {recipient}: {e}")
                
        return success
