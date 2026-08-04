"use client";

import { useEffect } from "react";
import { Provider } from "react-redux";
import { store, USE_MOCK } from "@/store";
import { useAppDispatch } from "@/store/hooks";
import { fetchDatasets } from "@/store/slices/datasetSlice";

/**
 * Loads the dataset list on first mount (skipped when USE_MOCK is true,
 * because the store is already pre-populated via preloadedState).
 */
function DataGate({ children }: { children: React.ReactNode }) {
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (USE_MOCK) return; // store already seeded
    dispatch(fetchDatasets());
  }, [dispatch]);

  return <>{children}</>;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <Provider store={store}>
      <DataGate>{children}</DataGate>
    </Provider>
  );
}
