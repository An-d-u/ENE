"""
GPT-SoVITS TTS 클라이언트
"""
import aiohttp
import asyncio
from pathlib import Path


class TTSClient:
    """GPT-SoVITS API 클라이언트"""
    
    def __init__(
        self,
        api_url: str = "http://127.0.0.1:9880",
        ref_audio_path: str = "assets/ref_audio/refvoice.wav",
        ref_text: str = "人間さんはどんな色が一番好き？ ん？ なんで聞いたかって？ ふふん～ 内緒",
        ref_language: str = "ja",
        target_language: str = "ja"
    ):
        """
        GPT-SoVITS TTS 클라이언트 초기화
        
        Args:
            api_url: GPT-SoVITS API URL
            ref_audio_path: 참조 오디오 파일 경로
            ref_text: 참조 오디오의 텍스트
            ref_language: 참조 오디오 언어 코드
            target_language: 출력 언어 코드
        """
        self.api_url = api_url.rstrip('/')
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.ref_language = ref_language
        self.target_language = target_language
        
        print(f"[TTS] Initialized with API: {self.api_url}")
        print(f"[TTS] Reference audio: {self.ref_audio_path}")

    @staticmethod
    def _normalize_tts_text(text: str) -> str:
        """
        GPT-SoVITS 전송 전 텍스트 줄바꿈을 정규화한다.
        - CRLF/CR -> LF
        - 연속 빈 줄 축약
        - 줄 앞뒤 공백 정리
        """
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        normalized_lines = [line.strip() for line in normalized.split("\n")]

        compact_lines = []
        prev_blank = False
        for line in normalized_lines:
            is_blank = (line == "")
            if is_blank and prev_blank:
                continue
            compact_lines.append(line)
            prev_blank = is_blank

        return "\n".join(compact_lines).strip()
    
    async def generate_speech(self, text: str) -> bytes:
        """
        텍스트를 음성으로 변환
        
        Args:
            text: 합성할 일본어 텍스트
            
        Returns:
            오디오 데이터 (WAV bytes)
            
        Raises:
            Exception: TTS 생성 실패 시
        """
        normalized_text = self._normalize_tts_text(text)
        if not normalized_text:
            raise ValueError("Text cannot be empty")
        
        print(f"[TTS] Generating speech for: {normalized_text[:50]}...")
        
        try:
            # 참조 오디오 파일 존재 여부 확인
            ref_path = Path(self.ref_audio_path)
            if not ref_path.exists():
                raise FileNotFoundError(f"Reference audio not found: {self.ref_audio_path}")
            
            # API 요청 파라미터
            params = {
                "text": normalized_text,
                "text_lang": self.target_language,
                "ref_audio_path": str(ref_path.absolute()),
                "prompt_text": self.ref_text,
                "prompt_lang": self.ref_language,
            }
            
            # HTTP 요청
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/tts",
                    json=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"TTS API error ({response.status}): {error_text}")
                    
                    # 오디오 데이터 받기
                    audio_data = await response.read()
                    print(f"[TTS] Generated {len(audio_data)} bytes of audio")
                    
                    return audio_data
        
        except asyncio.TimeoutError:
            raise Exception("TTS API timeout - server may be offline")
        except aiohttp.ClientError as e:
            raise Exception(f"TTS API connection error: {e}")
        except Exception as e:
            print(f"[TTS] Error: {e}")
            raise
    
    def is_available(self) -> bool:
        """
        TTS 서비스 사용 가능 여부 확인
        
        Returns:
            True if available, False otherwise
        """
        # 참조 오디오 파일 존재 여부만 확인 (동기적)
        return Path(self.ref_audio_path).exists()
