/** The star toggle on a map card and on a table row. */
export function FavouriteStar({
  name,
  starred,
  disabled,
  onToggle,
}: {
  name: string;
  starred: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      className={`star${starred ? " star-on" : ""}`}
      aria-pressed={starred}
      aria-label={
        starred ? `Remove ${name} from favourites` : `Add ${name} to favourites`
      }
      title={starred ? "Favourite" : "Add to favourites"}
      disabled={disabled}
      onClick={onToggle}
    >
      <span aria-hidden="true">{starred ? "★" : "☆"}</span>
    </button>
  );
}
