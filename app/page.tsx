export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <div className="flex items-center gap-3">
        <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
        <h1 className="font-mono text-2xl font-semibold tracking-widest text-foreground">
          ZENTRYX
        </h1>
      </div>
      <p className="font-mono text-sm text-muted-foreground tracking-wider">
        Copy-Trading Intelligence Terminal &mdash; initializing...
      </p>
    </main>
  );
}
