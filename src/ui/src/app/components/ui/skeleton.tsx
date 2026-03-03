import { cn } from './utils';

function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      className={cn('bg-accent rounded-ui animate-pulse', className)}
      {...props}
    />
  );
}

export { Skeleton };
