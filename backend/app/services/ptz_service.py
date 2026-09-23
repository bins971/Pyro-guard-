import logging
from typing import Tuple

try:
    from onvif import ONVIFCamera
    ONVIF_AVAILABLE = True
except ImportError:
    ONVIF_AVAILABLE = False

logger = logging.getLogger(__name__)

class PTZController:
    def __init__(self):
        self.active_cameras = {}
        if not ONVIF_AVAILABLE:
            logger.info("onvif-zeep not installed — PTZ running in simulation mode (no PTZ camera attached).")

    def _connect_camera(self, ip: str, port: int, user: str, password: str):
        if not ONVIF_AVAILABLE:
            return None
            
        cam_key = f"{ip}:{port}"
        if cam_key in self.active_cameras:
            return self.active_cameras[cam_key]

        try:
            # We assume ONVIF WSDL files are installed via the library or we use the remote path
            mycam = ONVIFCamera(ip, port, user, password)                                                                                                                                                                                                                                                                                                                                                                                                   
            ptz = mycam.create_ptz_service()
            media = mycam.create_media_service()
            profiles = media.GetProfiles()
            
            if not profiles:
                logger.error(f"PTZ Error: No profiles found on {ip}")
                return None
                
            media_profile = profiles[0]
            request = ptz.create_type('GetConfigurationOptions')
            request.ConfigurationToken = media_profile.PTZConfiguration.token
            ptz_configuration_options = ptz.GetConfigurationOptions(request)
            
            self.active_cameras[cam_key] = {
                'cam': mycam,
                'ptz': ptz,
                'profile': media_profile,
                'options': ptz_configuration_options
            }
            logger.info(f"Successfully connected to PTZ camera at {ip}")
            return self.active_cameras[cam_key]
        except Exception as e:
            logger.error(f"Failed to connect to PTZ camera {ip}:{port} - {e}")
            return None

    def track_target(self, camera_model, bounding_box: Tuple[int, int, int, int], frame_width: int, frame_height: int):
        if not camera_model.ptz_enabled:
            return

        x1, y1, x2, y2 = bounding_box
        target_center_x = (x1 + x2) / 2.0
        target_center_y = (y1 + y2) / 2.0
        
        frame_center_x = frame_width / 2.0
        frame_center_y = frame_height / 2.0
        
        # Calculate offset (-1.0 to 1.0 range where 0 is center)
        pan_offset = (target_center_x - frame_center_x) / frame_center_x
        tilt_offset = (frame_center_y - target_center_y) / frame_center_y 

        # Deadzone so it doesn't constantly twitch
        if abs(pan_offset) < 0.15 and abs(tilt_offset) < 0.15:
            return

        logger.info(f"[PTZ SIMULATION] Camera {camera_model.id}: Panning by {pan_offset:.2f}, Tilting by {tilt_offset:.2f}")

        if not ONVIF_AVAILABLE:
            return

        # Extract IP from RTSP URL for ONVIF connection
        # Example RTSP: rtsp://user:pass@192.168.1.100:554/stream
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(camera_model.rtsp_url)
            ip = parsed.hostname
            if not ip:
                return
        except:
            return

        ptz_data = self._connect_camera(
            ip, 
            camera_model.ptz_port or 80, 
            camera_model.ptz_user, 
            camera_model.ptz_password
        )
        
        if not ptz_data:
            return

        try:
            ptz = ptz_data['ptz']
            request = ptz.create_type('ContinuousMove')
            request.ProfileToken = ptz_data['profile'].token
            
            # Create velocity
            velocity = ptz.GetStatus({'ProfileToken': ptz_data['profile'].token}).Position
            velocity.PanTilt.x = max(-1.0, min(1.0, pan_offset * 0.5)) 
            velocity.PanTilt.y = max(-1.0, min(1.0, tilt_offset * 0.5))
            request.Velocity = velocity
            
            ptz.ContinuousMove(request)
            
            # Stop after brief movement to re-evaluate next frame
            import time
            time.sleep(0.2)
            stop_req = ptz.create_type('Stop')
            stop_req.ProfileToken = ptz_data['profile'].token
            stop_req.PanTilt = True
            stop_req.Zoom = False
            ptz.Stop(stop_req)
            
        except Exception as e:
            logger.error(f"Failed to move PTZ camera {camera_model.id} - {e}")
