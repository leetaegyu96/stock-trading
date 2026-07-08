// 캐릭터 상세 페이지 자리표시자. 실제 구현은 Task 12에서 진행한다.
import { Link, useParams } from "react-router-dom";

export function Detail() {
  const { name } = useParams<{ name: string }>();

  return (
    <div className="main-page">
      <p>
        <Link to="/">← 메인으로</Link>
      </p>
      <h1 className="main-page__title">{name ?? "알 수 없음"}</h1>
      <p className="main-page__state">상세 화면은 준비 중입니다.</p>
    </div>
  );
}

export default Detail;
