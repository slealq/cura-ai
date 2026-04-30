interface SightLabLogoProps {
  size?: 'sm' | 'lg';
  className?: string;
}

export default function SightLabLogo({ size = 'sm', className }: SightLabLogoProps) {
  const px = size === 'lg' ? 40 : 32;
  // Unique ID per instance to avoid SVG gradient collisions
  const id = size;

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <defs>
        {/* Chromatic spectrum gradient — flows across the eye */}
        <linearGradient id={`chromatic-${id}`} x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#8b5cf6">
            <animate attributeName="stop-color" values="#8b5cf6;#3b82f6;#06b6d4;#10b981;#f59e0b;#ef4444;#8b5cf6" dur="6s" repeatCount="indefinite" />
          </stop>
          <stop offset="33%" stopColor="#3b82f6">
            <animate attributeName="stop-color" values="#3b82f6;#06b6d4;#10b981;#f59e0b;#ef4444;#8b5cf6;#3b82f6" dur="6s" repeatCount="indefinite" />
          </stop>
          <stop offset="66%" stopColor="#10b981">
            <animate attributeName="stop-color" values="#10b981;#f59e0b;#ef4444;#8b5cf6;#3b82f6;#06b6d4;#10b981" dur="6s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%" stopColor="#f59e0b">
            <animate attributeName="stop-color" values="#f59e0b;#ef4444;#8b5cf6;#3b82f6;#06b6d4;#10b981;#f59e0b" dur="6s" repeatCount="indefinite" />
          </stop>
        </linearGradient>

        {/* Spark gradient — warm tones */}
        <linearGradient id={`spark-${id}`} x1="40" y1="8" x2="56" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#fbbf24">
            <animate attributeName="stop-color" values="#fbbf24;#f97316;#fbbf24" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%" stopColor="#f97316">
            <animate attributeName="stop-color" values="#f97316;#fbbf24;#f97316" dur="3s" repeatCount="indefinite" />
          </stop>
        </linearGradient>
      </defs>

      {/* Outer eye shape */}
      <path
        d="M4 32C4 32 16 12 32 12C48 12 60 32 60 32C60 32 48 52 32 52C16 52 4 32 4 32Z"
        stroke={`url(#chromatic-${id})`}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />

      {/* Iris ring */}
      <circle
        cx="32"
        cy="32"
        r="11"
        stroke={`url(#chromatic-${id})`}
        strokeWidth="3"
        fill="none"
      />

      {/* Pupil — chromatic fill */}
      <circle
        cx="32"
        cy="32"
        r="5"
        fill={`url(#chromatic-${id})`}
      />

      {/* Spark — top-right */}
      <path
        d="M48 8L50 14L56 16L50 18L48 24L46 18L40 16L46 14Z"
        fill={`url(#spark-${id})`}
      />

      {/* Spark dot — small accent */}
      <circle cx="55" cy="10" r="1.5" fill={`url(#spark-${id})`} />
    </svg>
  );
}
