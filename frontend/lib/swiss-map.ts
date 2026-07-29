import { geoContains, geoMercator, geoPath } from "d3-geo";
import type { FeatureCollection, Geometry } from "geojson";
import type {
  GeometryCollection,
  Topology,
} from "topojson-specification";
import { feature } from "topojson-client";

import swissTopologyData from "swiss-maps/2026/ch-combined.json";

export const SWISS_MAP_WIDTH = 800;
export const SWISS_MAP_HEIGHT = 400;

const CANTON_NAMES = [
  "Zürich",
  "Bern",
  "Luzern",
  "Uri",
  "Schwyz",
  "Obwalden",
  "Nidwalden",
  "Glarus",
  "Zug",
  "Fribourg",
  "Solothurn",
  "Basel-Stadt",
  "Basel-Landschaft",
  "Schaffhausen",
  "Appenzell Ausserrhoden",
  "Appenzell Innerrhoden",
  "St. Gallen",
  "Graubünden",
  "Aargau",
  "Thurgau",
  "Ticino",
  "Vaud",
  "Valais",
  "Neuchâtel",
  "Geneva",
  "Jura",
] as const;

const topology = swissTopologyData as unknown as Topology<{
  cantons: GeometryCollection;
}>;
const cantons = feature(
  topology,
  topology.objects.cantons,
) as FeatureCollection<Geometry>;

// One shared geographic projection keeps the official canton geometry and job
// coordinates aligned inside the same SVG view box.
const projection = geoMercator().fitExtent(
  [
    [12, 12],
    [SWISS_MAP_WIDTH - 12, SWISS_MAP_HEIGHT - 12],
  ],
  cantons,
);
const path = geoPath(projection);

export const swissCantonPaths = cantons.features
  .map((canton, index) => ({
    id: index,
    path: path(canton),
  }))
  .filter(
    (canton): canton is { id: number; path: string } =>
      canton.path !== null,
  );

export function projectSwissCoordinates(
  longitude: number,
  latitude: number,
) {
  const coordinates = projection([longitude, latitude]);
  return {
    x: coordinates?.[0] ?? 0,
    y: coordinates?.[1] ?? 0,
  };
}

export function jobsByCanton(
  points: Array<{
    latitude: number;
    longitude: number;
    job_count: number;
  }>,
) {
  const counts = CANTON_NAMES.map((name, index) => ({
    id: index + 1,
    name,
    jobCount: 0,
  }));

  for (const point of points) {
    const canton = cantons.features.find((feature) =>
      geoContains(feature, [point.longitude, point.latitude]),
    );
    const cantonId = Number(canton?.id);
    if (cantonId >= 1 && cantonId <= counts.length) {
      counts[cantonId - 1].jobCount += point.job_count;
    }
  }

  return counts.sort(
    (first, second) =>
      second.jobCount - first.jobCount ||
      first.name.localeCompare(second.name),
  );
}
