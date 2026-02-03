"""
장기기억 시스템 테스트
"""
import asyncio
from pathlib import Path

# 임포트 테스트
try:
    from src.ai.memory_types import create_memory_entry
    from src.ai.embedding import EmbeddingGenerator
    from src.ai.memory import MemoryManager
    print("✅ 모든 모듈 임포트 성공")
except Exception as e:
    print(f"❌ 임포트 실패: {e}")
    exit(1)


async def test_memory_system():
    """기본 기능 테스트"""
    
    print("\n=== 장기기억 시스템 테스트 ===\n")
    
    # 1. 임베딩 생성기 테스트 (API 키 필요)
    print("1. 임베딩 생성기 테스트...")
    voyage_key_file = Path("voyage_api_key.txt")
    
    if not voyage_key_file.exists():
        print("⚠️  voyage_api_key.txt 파일이 없습니다.")
        print("   Voyage AI API 키를 파일에 저장해주세요.")
        embedding_gen = None
    else:
        voyage_key = voyage_key_file.read_text(encoding='utf-8').strip()
        
        if voyage_key == "your-voyage-api-key-here":
            print("⚠️  Voyage AI API 키를 설정해주세요.")
            embedding_gen = None
        else:
            try:
                embedding_gen = EmbeddingGenerator(api_key=voyage_key)
                
                # 간단한 테스트
                test_text = "안녕하세요, 테스트입니다."
                embedding = await embedding_gen.embed(test_text)
                print(f"   ✅ 임베딩 생성 성공 (차원: {len(embedding)})")
                
                # 유사도 테스트
                text1 = "오늘 날씨가 좋아요"
                text2 = "날씨가 정말 맑네요"
                text3 = "피자를 먹었어요"
                
                emb1 = await embedding_gen.embed(text1)
                emb2 = await embedding_gen.embed(text2)
                emb3 = await embedding_gen.embed(text3)
                
                sim_12 = embedding_gen.cosine_similarity(emb1, emb2)
                sim_13 = embedding_gen.cosine_similarity(emb1, emb3)
                
                print(f"   유사도 (날씨-날씨): {sim_12:.3f}")
                print(f"   유사도 (날씨-피자): {sim_13:.3f}")
                
            except Exception as e:
                print(f"   ❌ 임베딩 생성 실패: {e}")
                embedding_gen = None
    
    # 2. 메모리 항목 생성 테스트
    print("\n2. 메모리 항목 생성 테스트...")
    memory = create_memory_entry(
        summary="마스터가 파이썬 프로그래밍에 대해 질문했음",
        original_messages=["파이썬 어떻게 배워?", "기초부터 하나씩 배우시면 좋아요."],
        is_important=True,
        tags=["프로그래밍", "파이썬"]
    )
    print(f"   ✅ 메모리 생성: {memory}")
    
    # 3. 메모리 매니저 테스트
    print("\n3. 메모리 매니저 테스트...")
    memory_file = "test_memory.json"
    manager = MemoryManager(memory_file, embedding_gen)
    
    # 기억 추가
    await manager.add_summary(
        summary="마스터가 오늘 프로젝트 마감일이라고 말했음",
        original_messages=["오늘 프로젝트 마감일이야", "힘내세요, 마스터!"],
        is_important=True
    )
    
    await manager.add_summary(
        summary="마스터가 좋아하는 음식은 피자라고 말함",
        original_messages=["나 피자 좋아해", "아, 그렇군요!"],
        tags=["음식", "선호도"]
    )
    
    print(f"   ✅ 기억 저장 완료")
    
    # 통계
    stats = manager.get_stats()
    print(f"   총 기억: {stats['total']}")
    print(f"   중요 기억: {stats['important']}")
    print(f"   임베딩 포함: {stats['with_embedding']}")
    
    # 4. 검색 테스트
    if embedding_gen:
        print("\n4. 유사도 검색 테스트...")
        results = await manager.find_similar("프로젝트는 어떻게 되고 있어?", top_k=2)
        
        if results:
            print("   검색 결과:")
            for memory, sim in results:
                print(f"   - [{sim:.3f}] {memory.summary}")
        else:
            print("   검색 결과 없음")
    
    # 5. 최근 기억 테스트
    print("\n5. 최근 기억 조회...")
    recent = manager.get_recent(count=2)
    for mem in recent:
        print(f"   - {mem.timestamp[:19]} : {mem.summary}")
    
    # 정리
    print("\n✅ 모든 테스트 완료!")
    
    # 테스트 파일 삭제
    if Path(memory_file).exists():
        Path(memory_file).unlink()
        print(f"   테스트 파일 삭제: {memory_file}")


if __name__ == "__main__":
    asyncio.run(test_memory_system())
