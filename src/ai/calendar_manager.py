"""
캘린더 관리 시스템
일정 추가/조회 및 대화 횟수 추적
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import List, Dict
import uuid

from ..core.app_paths import resolve_user_storage_path


@dataclass
class CalendarEvent:
    """캘린더 일정 데이터"""
    id: str
    date: str  # ISO format (YYYY-MM-DD)
    title: str
    description: str
    created_at: str
    source: str  # "user" or "ai_extracted"
    completed: bool = False  # 완료 여부
    
    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CalendarEvent':
        """딕셔너리에서 복원"""
        return cls(**data)


class CalendarManager:
    """캘린더 관리자"""
    
    def __init__(self, calendar_file: str | Path | None = None):
        """
        Args:
            calendar_file: 캘린더 데이터 저장 파일
        """
        target_file = calendar_file if calendar_file is not None else "calendar.json"
        self.calendar_file = resolve_user_storage_path(target_file)
        self.events: List[CalendarEvent] = []
        self.conversation_counts: Dict[str, int] = {}
        self.head_pat_counts: Dict[str, int] = {}
        self.load()
    
    def load(self):
        """캘린더 데이터 로드"""
        if self.calendar_file.exists():
            try:
                with open(self.calendar_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.events = [CalendarEvent.from_dict(e) for e in data.get('events', [])]
                    self.conversation_counts = data.get('conversation_counts', {})
                    self.head_pat_counts = data.get('head_pat_counts', {})
                print(f"[Calendar] 로드 완료: {len(self.events)}개 일정, {len(self.conversation_counts)}일 대화 기록")
            except Exception as e:
                print(f"[Calendar] 로드 실패: {e}")
                self.events = []
                self.conversation_counts = {}
                self.head_pat_counts = {}
        else:
            print("[Calendar] 새 캘린더 파일 생성 예정")
    
    def save(self):
        """캘린더 데이터 저장"""
        try:
            self.calendar_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'events': [e.to_dict() for e in self.events],
                'conversation_counts': self.conversation_counts,
                'head_pat_counts': self.head_pat_counts,
            }
            with open(self.calendar_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("[Calendar] 저장 완료")
        except Exception as e:
            print(f"[Calendar] 저장 실패: {e}")
    
    def add_event(
        self,
        date: str,
        title: str,
        description: str = "",
        source: str = "user"
    ) -> CalendarEvent:
        """
        일정 추가
        
        Args:
            date: 날짜 (YYYY-MM-DD)
            title: 일정 제목
            description: 상세 설명
            source: 출처 ("user" 또는 "ai_extracted")
            
        Returns:
            생성된 CalendarEvent
        """
        event = CalendarEvent(
            id=str(uuid.uuid4()),
            date=date,
            title=title,
            description=description,
            created_at=datetime.now().isoformat(),
            source=source
        )
        self.events.append(event)
        self.save()
        print(f"[Calendar] 일정 추가: {date} - {title}")
        return event
    
    def get_events_by_date(self, date: str) -> List[CalendarEvent]:
        """
        특정 날짜의 일정 조회
        
        Args:
            date: 날짜 (YYYY-MM-DD)
            
        Returns:
            해당 날짜의 일정 리스트
        """
        return [e for e in self.events if e.date == date]
    
    def get_upcoming_events(self, days: int = 3) -> List[CalendarEvent]:
        """
        다가오는 일정 조회 (오늘 ~ days일 후)
        
        Args:
            days: 조회할 일수
            
        Returns:
            다가오는 일정 리스트 (날짜순 정렬)
        """
        today = datetime.now().date()
        end_date = today + timedelta(days=days)
        
        upcoming = []
        for event in self.events:
            try:
                event_date = datetime.fromisoformat(event.date).date()
                if today <= event_date <= end_date:
                    upcoming.append(event)
            except ValueError:
                pass  # 잘못된 날짜 형식 무시
        
        return sorted(upcoming, key=lambda e: e.date)
    
    def delete_event(self, event_id: str):
        """
        일정 삭제
        
        Args:
            event_id: 일정 ID
        """
        self.events = [e for e in self.events if e.id != event_id]
        self.save()
        print(f"[Calendar] 일정 삭제: {event_id}")
    
    def toggle_event_completion(self, event_id: str) -> bool:
        """
        일정 완료 상태 토글
        
        Args:
            event_id: 일정 ID
            
        Returns:
            새로운 완료 상태
        """
        for event in self.events:
            if event.id == event_id:
                event.completed = not event.completed
                self.save()
                print(f"[Calendar] 일정 완료 상태 변경: {event_id} -> {event.completed}")
                return event.completed
        return False
    
    def increment_conversation_count(self, date: str = None):
        """
        대화 횟수 증가
        
        Args:
            date: 날짜 (기본값: 오늘)
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        self.conversation_counts[date] = self.conversation_counts.get(date, 0) + 1
        self.save()
    
    def get_conversation_count(self, date: str) -> int:
        """
        특정 날짜의 대화 횟수 조회
        
        Args:
            date: 날짜 (YYYY-MM-DD)
            
        Returns:
            대화 횟수
        """
        return self.conversation_counts.get(date, 0)

    def increment_head_pat_count(self, date: str = None):
        """Increment head pat count for a specific date."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        self.head_pat_counts[date] = self.head_pat_counts.get(date, 0) + 1
        self.save()

    def get_head_pat_count(self, date: str) -> int:
        """Return head pat count for a specific date."""
        return self.head_pat_counts.get(date, 0)
    
    def get_recent_conversation_counts(self, days: int = 7, exclude_today: bool = True) -> Dict[str, int]:
        """
        최근 N일간의 대화 횟수 반환
        
        Args:
            days: 조회할 일수
            exclude_today: 오늘 제외 여부
            
        Returns:
            {날짜: 횟수} 딕셔너리 (날짜 내림차순)
        """
        from datetime import datetime, timedelta
        
        today = datetime.now().date()
        start_offset = 1 if exclude_today else 0
        
        recent_counts = {}
        for i in range(start_offset, days + start_offset):
            date = today - timedelta(days=i)
            date_str = date.isoformat()
            count = self.conversation_counts.get(date_str, 0)
            if count > 0:  # 0보다 큰 경우만 포함
                recent_counts[date_str] = count
        
        # 날짜 내림차순 정렬
        return dict(sorted(recent_counts.items(), reverse=True))

    def get_recent_or_latest_conversation_counts(self, days: int = 7, exclude_today: bool = True) -> Dict[str, int]:
        """
        최근 N일 대화 기록이 있으면 그것을 반환하고,
        없으면 전체 기록 중 가장 최근 대화 1건만 반환한다.

        Args:
            days: 우선 조회할 최근 일수
            exclude_today: 오늘 제외 여부

        Returns:
            {날짜: 횟수} 딕셔너리
        """
        recent_counts = self.get_recent_conversation_counts(days=days, exclude_today=exclude_today)
        if recent_counts:
            return recent_counts

        valid_items = []
        for date_str, count in self.conversation_counts.items():
            if count <= 0:
                continue
            try:
                date_obj = datetime.fromisoformat(date_str).date()
            except ValueError:
                continue
            valid_items.append((date_obj, date_str, count))

        if not valid_items:
            return {}

        valid_items.sort(reverse=True)
        _, latest_date_str, latest_count = valid_items[0]
        return {latest_date_str: latest_count}
    
    def get_all_events(self) -> List[CalendarEvent]:
        """모든 일정 반환"""
        return sorted(self.events, key=lambda e: e.date)
    
    def get_stats(self) -> Dict:
        """통계 반환"""
        return {
            'total_events': len(self.events),
            'total_conversation_days': len(self.conversation_counts),
            'total_conversations': sum(self.conversation_counts.values()),
            'total_head_pat_days': len(self.head_pat_counts),
            'total_head_pats': sum(self.head_pat_counts.values()),
        }
