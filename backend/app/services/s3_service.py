import logging
import os

try:
    import boto3
    from botocore.exceptions import ClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False
    ClientError = Exception  # Fallback for type reference

from ..config import settings

logger = logging.getLogger(__name__)

class S3Service:
    def __init__(self):
        self.bucket_name = settings.AWS_S3_BUCKET
        self.region = settings.AWS_REGION
        self.enabled = bool(self.bucket_name and settings.AWS_ACCESS_KEY_ID and _BOTO3_AVAILABLE)
        
        if not _BOTO3_AVAILABLE:
            logger.info("S3 Storage disabled (boto3 not installed)")
            return
        
        if self.enabled:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=self.region
                )
                logger.info(f"S3 Storage enabled on bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
                self.enabled = False
        else:
            logger.info("S3 Storage disabled (no bucket/keys provided)")

    def upload_image(self, file_path: str) -> str:
        if not self.enabled or not os.path.exists(file_path):
            return ""

        file_name = os.path.basename(file_path)
        try:
            self.s3_client.upload_file(
                file_path, 
                self.bucket_name, 
                file_name,
                ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/jpeg'}
            )
            
            url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{file_name}"
            logger.info(f"Image uploaded to S3: {url}")
            return url
        except ClientError as e:
            logger.error(f"Error uploading to S3: {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected S3 error: {e}")
            return ""
