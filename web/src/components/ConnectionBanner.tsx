export function ConnectionBanner({ connected }: { connected: boolean }) {
  if (connected) return null;
  return (
    <div className="connection-banner" role="status">
      Disconnected from the panel — reconnecting…
    </div>
  );
}
