/**
 * ENE 웹 런타임 로더 마커.
 *
 * 실제 런타임은 index.html의 순서 지정 classic script로 분리되어 있다.
 * 패키징과 테스트가 안정적인 진입점을 갖도록 이 파일은 마지막에 둔다.
 */
console.log("=== ENE web runtime chunks loaded ===");
