"""
Alert service for email notifications using Brevo (formerly Sendinblue)
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import List, Optional
from datetime import datetime
import os
from ..config import settings


class AlertService:
    """
    Handles alert notifications via email using Brevo SMTP
    
    Brevo Configuration:
    - SMTP Host: smtp-relay.brevo.com
    - SMTP Port: 587 (TLS)
    - Get your SMTP credentials from: https://app.brevo.com/settings/keys/smtp
    """
    
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
        """
        Send fire alert via email
        
        Args:
            camera_name: Name of the camera
            location: Camera location
            fire_level: Detected fire level (0-3)
            confidence: Detection confidence
            timestamp: Detection timestamp
            image_path: Path to detection image
            recipients: List of email recipients
        
        Returns:
            True if email sent successfully
        """
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
            
            html_body = f"""
            <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; }}
                        .alert-box {{
                            border: 3px solid {'#EF4444' if fire_level >= 2 else '#FBBF24'};
                            border-radius: 10px;
                            padding: 20px;
                            margin: 20px;
                            background-color: #FEF2F2;
                        }}
                        .level-badge {{
                            display: inline-block;
                            padding: 10px 20px;
                            border-radius: 5px;
                            background-color: {'#EF4444' if fire_level == 3 else '#F97316' if fire_level == 2 else '#FBBF24'};
                            color: white;
                            font-weight: bold;
                            font-size: 18px;
                        }}
                        .info-table {{
                            width: 100%;
                            border-collapse: collapse;
                            margin-top: 20px;
                        }}
                        .info-table td {{
                            padding: 10px;
                            border-bottom: 1px solid #ddd;
                        }}
                        .info-table td:first-child {{
                            font-weight: bold;
                            width: 150px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="alert-box">
                        <h1>{level_emojis.get(fire_level, '🔥')} FIRE DETECTION ALERT</h1>
                        <div class="level-badge">
                            Level {fire_level}: {level_names.get(fire_level, 'Unknown')}
                        </div>
                        
                        <table class="info-table">
                            <tr>
                                <td>Camera:</td>
                                <td>{camera_name}</td>
                            </tr>
                            <tr>
                                <td>Location:</td>
                                <td>{location or 'N/A'}</td>
                            </tr>
                            <tr>
                                <td>Fire Level:</td>
                                <td>{level_names.get(fire_level, 'Unknown')}</td>
                            </tr>
                            <tr>
                                <td>Confidence:</td>
                                <td>{confidence * 100:.1f}%</td>
                            </tr>
                            <tr>
                                <td>Detected At:</td>
                                <td>{timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
                            </tr>
                        </table>
                        
                        <p style="margin-top: 20px; color: #DC2626; font-weight: bold;">
                            ⚠️ Please take immediate action and verify the situation.
                        </p>
                    </div>
                </body>
            </html>
            """
            
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
    

