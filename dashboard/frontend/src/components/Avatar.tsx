// 성과연동 표정 아바타. 커스텀 인라인 SVG (외부 자산/네트워크 의존 없음).
// 캐릭터별 정체성(국내형/해외형/범용형)은 색상 + 소품(태극/지구본)으로 구분하고,
// mood(표정)는 성과(오늘 등락/TWR)에서 매핑되어 눈/입 모양으로 표현된다.
import type { Mood } from "./mood";

export type { Mood };

export type CharacterVariant = "domestic" | "global" | "mixed";

export interface AvatarProps {
  character: string;
  mood: Mood;
  /** px 단위 정사각형 크기. 기본 64. */
  size?: number;
  className?: string;
}

/** 캐릭터명 문자열에서 정체성(국내형/해외형/범용형)을 결정한다.
 * 알려지지 않은 이름은 문자 코드 합을 이용해 3가지 중 하나로 결정론적으로 배정한다
 * (동일 이름 → 항상 동일 variant, 렌더마다 흔들리지 않음). */
export function characterVariant(character: string): CharacterVariant {
  if (character.includes("국내")) return "domestic";
  if (character.includes("해외") || character.includes("글로벌")) return "global";
  if (character.includes("범용") || character.includes("혼합")) return "mixed";
  let hash = 0;
  for (let i = 0; i < character.length; i += 1) {
    hash = (hash * 31 + character.charCodeAt(i)) % 3;
  }
  const fallback: CharacterVariant[] = ["domestic", "global", "mixed"];
  return fallback[hash];
}

interface VariantTheme {
  skin: string;
  cheek: string;
  ring: string;
}

const VARIANT_THEME: Record<CharacterVariant, VariantTheme> = {
  // 국내형 — 태극/원화 느낌 (한국 관례 상 태극기의 홍/청)
  domestic: { skin: "#FFE3B3", cheek: "#FF8A80", ring: "#C62828" },
  // 해외형 — 글로벌/달러 느낌 (지구본 블루/그린)
  global: { skin: "#FFE3B3", cheek: "#80CBC4", ring: "#1565C0" },
  // 범용형 — 혼합 (보라/골드)
  mixed: { skin: "#FFE3B3", cheek: "#CE93D8", ring: "#6A1B9A" },
};

/** mood 별 눈/입 SVG 조각. viewBox 0 0 100 100 기준 좌표. */
function FaceFeatures({ mood }: { mood: Mood }) {
  switch (mood) {
    case "happy":
      return (
        <>
          {/* 활짝 웃는 반달눈 */}
          <path d="M28 44 Q35 36 42 44" stroke="#3E2723" strokeWidth="3.2" strokeLinecap="round" fill="none" />
          <path d="M58 44 Q65 36 72 44" stroke="#3E2723" strokeWidth="3.2" strokeLinecap="round" fill="none" />
          {/* 크게 벌어진 입 (활짝 웃음) */}
          <path d="M32 60 Q50 82 68 60 Q50 74 32 60 Z" fill="#B71C1C" stroke="#3E2723" strokeWidth="1.5" />
          <path d="M38 63 Q50 70 62 63" fill="#fff" opacity="0.85" />
        </>
      );
    case "smile":
      return (
        <>
          <circle cx="35" cy="43" r="4.5" fill="#3E2723" />
          <circle cx="65" cy="43" r="4.5" fill="#3E2723" />
          {/* 부드러운 미소 곡선 */}
          <path d="M34 62 Q50 74 66 62" stroke="#3E2723" strokeWidth="3.2" strokeLinecap="round" fill="none" />
        </>
      );
    case "neutral":
      return (
        <>
          <circle cx="35" cy="43" r="4.5" fill="#3E2723" />
          <circle cx="65" cy="43" r="4.5" fill="#3E2723" />
          {/* 무표정 직선 입 */}
          <line x1="36" y1="66" x2="64" y2="66" stroke="#3E2723" strokeWidth="3.2" strokeLinecap="round" />
        </>
      );
    case "down":
    default:
      return (
        <>
          {/* 살짝 처진 눈썹 (화남이 아니라 시무룩 — 안쪽이 위로) */}
          <line x1="28" y1="37" x2="41" y2="34.5" stroke="#3E2723" strokeWidth="2.4" strokeLinecap="round" />
          <line x1="72" y1="37" x2="59" y2="34.5" stroke="#3E2723" strokeWidth="2.4" strokeLinecap="round" />
          <circle cx="35" cy="45" r="4" fill="#3E2723" />
          <circle cx="65" cy="45" r="4" fill="#3E2723" />
          {/* 완만하게 처진 입 */}
          <path d="M37 68 Q50 61 63 68" stroke="#3E2723" strokeWidth="3" strokeLinecap="round" fill="none" />
        </>
      );
  }
}

/** 국내형 소품: 태극(음양) 배지. */
function DomesticBadge() {
  return (
    <g transform="translate(50 14)">
      <circle r="9" fill="#fff" stroke="#3E2723" strokeWidth="1.2" />
      <path
        d="M0 -9 A4.5 4.5 0 0 1 0 0 A4.5 4.5 0 0 0 0 9 A9 9 0 0 1 0 -9 Z"
        fill="#C62828"
      />
      <path
        d="M0 -9 A4.5 4.5 0 0 0 0 0 A4.5 4.5 0 0 1 0 9 A9 9 0 0 0 0 -9 Z"
        fill="#1565C0"
      />
      <circle cy="-4.5" r="1.6" fill="#1565C0" />
      <circle cy="4.5" r="1.6" fill="#C62828" />
    </g>
  );
}

/** 해외형 소품: 지구본 배지. */
function GlobalBadge() {
  return (
    <g transform="translate(50 14)">
      <circle r="9" fill="#E3F2FD" stroke="#1565C0" strokeWidth="1.4" />
      <ellipse rx="9" ry="3.2" fill="none" stroke="#1565C0" strokeWidth="1" />
      <ellipse rx="3.2" ry="9" fill="none" stroke="#1565C0" strokeWidth="1" />
      <line x1="-9" y1="0" x2="9" y2="0" stroke="#1565C0" strokeWidth="1" />
    </g>
  );
}

/** 범용형 소품: 태극+지구본 혼합 배지. */
function MixedBadge() {
  return (
    <g transform="translate(50 14)">
      <circle r="9" fill="#F3E5F5" stroke="#6A1B9A" strokeWidth="1.2" />
      <path d="M0 -9 A4.5 4.5 0 0 1 0 0 A4.5 4.5 0 0 0 0 9 A9 9 0 0 1 0 -9 Z" fill="#C62828" opacity="0.85" />
      <path d="M0 -9 A4.5 4.5 0 0 0 0 0 A4.5 4.5 0 0 1 0 9 A9 9 0 0 0 0 -9 Z" fill="#1565C0" opacity="0.85" />
      <ellipse rx="9" ry="3.2" fill="none" stroke="#6A1B9A" strokeWidth="0.8" />
    </g>
  );
}

const VARIANT_BADGE: Record<CharacterVariant, () => JSX.Element> = {
  domestic: DomesticBadge,
  global: GlobalBadge,
  mixed: MixedBadge,
};

/**
 * 성과연동 표정 아바타. 캐릭터별 고유 색·소품 + mood에 따른 표정 변화를 담은
 * 자체 완결형(외부 자산/네트워크 불필요) 인라인 SVG.
 */
export function Avatar({ character, mood, size = 64, className }: AvatarProps) {
  const variant = characterVariant(character);
  const theme = VARIANT_THEME[variant];
  const Badge = VARIANT_BADGE[variant];

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label={`${character} 아바타 (표정: ${mood})`}
    >
      {/* 얼굴 — 얇은 링으로 정돈 */}
      <circle cx="50" cy="54" r="38" fill={theme.skin} stroke={theme.ring} strokeWidth="1.8" opacity="0.98" />
      {/* 볼터치 */}
      <circle cx="27" cy="59" r="5.5" fill={theme.cheek} opacity="0.5" />
      <circle cx="73" cy="59" r="5.5" fill={theme.cheek} opacity="0.5" />
      {/* 표정 (눈/입, mood에 따라 변경) */}
      <FaceFeatures mood={mood} />
      {/* 캐릭터 정체성 소품 (태극/지구본/혼합) */}
      <Badge />
    </svg>
  );
}

export default Avatar;
