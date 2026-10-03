import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";
import { ServiceError } from "@/shared/ui/service-error";
import type { CountTileView } from "../model/counts";

export interface CountTilesProps {
  tiles: readonly CountTileView[];
}

function Tile({ tile }: { tile: CountTileView }) {
  return (
    <li
      data-tile={tile.key}
      className="flex flex-col gap-2 rounded-lg border bg-surface-raised p-4 shadow-sm"
    >
      <h3 className="text-sm font-medium text-fg-muted">
        {tile.href === null ? (
          tile.title
        ) : (
          <Link href={tile.href as Route} className="text-primary hover:underline">
            {tile.title}
          </Link>
        )}
      </h3>
      {tile.error === null ? (
        <>
          <p data-slot="tile-value" className="text-3xl font-semibold tracking-tight text-fg">
            {tile.value}
          </p>
          {tile.detail === null ? null : <p className="text-sm text-fg-muted">{tile.detail}</p>}
        </>
      ) : (
        <ServiceError error={tile.error} className="p-3" />
      )}
      {tile.href === null ? (
        <p className="text-xs text-fg-muted">{t("admin.tile.notBuilt")}</p>
      ) : null}
    </li>
  );
}

/** The counts at the top of the admin home, one tile per list, each failing on its own. */
export function CountTiles({ tiles }: CountTilesProps) {
  return (
    <ul data-slot="count-tiles" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((tile) => (
        <Tile key={tile.key} tile={tile} />
      ))}
    </ul>
  );
}
