import { configureStore } from "@reduxjs/toolkit";
import datasetReducer from "./slices/datasetSlice";
import jobReducer from "./slices/jobSlice";

/**
 * Toggle this flag to `true` to pre-populate every component with
 * realistic mock data for UI development/demo.
 */
export const USE_MOCK = false;

export const store = configureStore({
  reducer: {
    dataset: datasetReducer,
    job: jobReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
