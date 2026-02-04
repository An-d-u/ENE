"""
사용자 프로필 관리
대화에서 추출한 사용자 정보 저장 및 관리
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
import json
from pathlib import Path


@dataclass
class ProfileFact:
    """사용자에 대한 단일 사실"""
    content: str
    category: str  # basic, preference, schedule, fact
    timestamp: str
    source: str = ""  # 어떤 대화에서 추출되었는지
    
    def to_dict(self) -> dict:
        return asdict(self)


class UserProfile:
    """사용자 프로필 관리"""
    
    def __init__(self, profile_file: str = "user_profile.json"):
        self.profile_file = Path(profile_file)
        self.facts: List[ProfileFact] = []
        
        # 구조화된 정보
        self.basic_info: Dict[str, str] = {}  # 이름, 생일 등
        self.preferences: Dict[str, List[str]] = {
            "likes": [],
            "dislikes": []
        }
        
        self.load()
    
    def load(self):
        """프로필 파일 로드"""
        if not self.profile_file.exists():
            print("[Profile] 프로필 파일 없음, 새로 생성")
            return
        
        try:
            with open(self.profile_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # facts 로드
            self.facts = [
                ProfileFact(**fact) for fact in data.get('facts', [])
            ]
            
            # 구조화된 정보 로드
            self.basic_info = data.get('basic_info', {})
            self.preferences = data.get('preferences', {"likes": [], "dislikes": []})
            
            print(f"[Profile] 로드 완료: {len(self.facts)}개 정보")
            
        except Exception as e:
            print(f"[Profile] 로드 실패: {e}")
    
    def save(self):
        """프로필 파일 저장"""
        try:
            data = {
                'facts': [fact.to_dict() for fact in self.facts],
                'basic_info': self.basic_info,
                'preferences': self.preferences,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.profile_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[Profile] 저장 완료: {len(self.facts)}개 정보")
            
        except Exception as e:
            print(f"[Profile] 저장 실패: {e}")
    
    def add_fact(self, content: str, category: str = "fact", source: str = ""):
        """새로운 사실 추가"""
        # 중복 체크 (비슷한 내용이 이미 있는지)
        for fact in self.facts:
            if fact.content.lower() == content.lower():
                print(f"[Profile] 중복 정보 무시: {content}")
                return
        
        fact = ProfileFact(
            content=content,
            category=category,
            timestamp=datetime.now().isoformat(),
            source=source
        )
        
        self.facts.append(fact)
        
        # 카테고리별 처리
        if category == "basic":
            self._update_basic_info(content)
        elif category == "preference":
            self._update_preferences(content)
        
        self.save()
        print(f"[Profile] 새 정보 추가: [{category}] {content}")
    
    def _update_basic_info(self, content: str):
        """기본 정보 업데이트 (간단한 파싱)"""
        content_lower = content.lower()
        
        if "이름" in content_lower or "name" in content_lower:
            # 나중에 더 정교한 파싱 가능
            pass
        elif "생일" in content_lower or "birthday" in content_lower:
            pass
    
    def _update_preferences(self, content: str):
        """선호도 업데이트"""
        content_lower = content.lower()
        
        if "좋아" in content_lower or "like" in content_lower:
            # 나중에 더 정교한 파싱 가능
            pass
        elif "싫어" in content_lower or "dislike" in content_lower:
            pass
    
    def get_facts_by_category(self, category: str) -> List[ProfileFact]:
        """카테고리별 정보 조회"""
        return [fact for fact in self.facts if fact.category == category]
    
    def get_all_facts(self) -> List[ProfileFact]:
        """모든 정보 조회"""
        return self.facts
    
    def delete_fact(self, index: int):
        """정보 삭제"""
        if 0 <= index < len(self.facts):
            deleted = self.facts.pop(index)
            self.save()
            print(f"[Profile] 정보 삭제: {deleted.content}")
    
    def get_context_string(self) -> str:
        """대화 컨텍스트용 문자열 생성"""
        if not self.facts:
            return ""
        
        lines = ["[마스터에 대해 알고 있는 정보]"]
        
        # 최근 10개만
        recent_facts = sorted(
            self.facts,
            key=lambda f: f.timestamp,
            reverse=True
        )[:10]
        
        for fact in recent_facts:
            lines.append(f"- {fact.content}")
        
        return "\n".join(lines)
