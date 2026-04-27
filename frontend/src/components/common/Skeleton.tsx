interface SkeletonProps {
  className?: string;
}

function Skeleton({ className = 'h-4 w-full' }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded bg-cream-dark ${className}`}
      aria-hidden="true"
    />
  );
}

export default Skeleton;
