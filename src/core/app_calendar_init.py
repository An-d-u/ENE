    def _init_calendar_manager(self):
        """캘린더 매니저 초기화"""
        from src.ai.calendar_manager import CalendarManager
        
        try:
            self.calendar_manager = CalendarManager()
            print("OK: 캘린더 매니저 초기화 성공")
            
            # Bridge에 연결
            if hasattr(self, 'overlay_window') and self.overlay_window:
                self.overlay_window.bridge.set_calendar_manager(self.calendar_manager)
                print("[App] Bridge에 캘린더 매니저 연결")
        except Exception as e:
            print(f"ERROR: 캘린더 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.calendar_manager = None
