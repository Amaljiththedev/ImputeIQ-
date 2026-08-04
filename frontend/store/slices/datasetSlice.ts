import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import { Dataset, DatasetResults, getDatasets, getDatasetResults } from "@/lib/api";

export type TabValue = "overview" | "diagnosis" | "imputation" | "explanation" | "sensitivity";

interface DatasetState {
  datasets: Dataset[];
  activeDatasetId: string | null;
  activeResults: DatasetResults | null;
  activeTab: TabValue;
  loading: boolean;
  error: string | null;
}

const initialState: DatasetState = {
  datasets: [],
  activeDatasetId: null,
  activeResults: null,
  activeTab: "overview",
  loading: false,
  error: null,
};

export const fetchDatasets = createAsyncThunk("dataset/fetchDatasets", async () => {
  return await getDatasets();
});

export const fetchResults = createAsyncThunk(
  "dataset/fetchResults",
  async (id: string) => {
    return await getDatasetResults(id);
  },
  {
    condition: (id: string, { getState }: { getState: () => any }) => {
      const { dataset } = getState();
      if (dataset.loading) {
        return false;
      }
      return true;
    },
  }
);

const datasetSlice = createSlice({
  name: "dataset",
  initialState,
  reducers: {
    setActiveTab(state, action: PayloadAction<TabValue>) {
      state.activeTab = action.payload;
    },
    setActiveDataset(state, action: PayloadAction<string | null>) {
      state.activeDatasetId = action.payload;
      if (action.payload !== state.activeResults?.dataset.id) {
        state.activeResults = null;
      }
      state.activeTab = "overview";
    },
    addDataset(state, action: PayloadAction<Dataset>) {
      state.datasets.unshift(action.payload);
    },
    /** Pre-populate the entire state with mock data in one dispatch. */
    seedMockState(
      state,
      action: PayloadAction<{
        datasets: Dataset[];
        activeDatasetId: string;
        activeResults: DatasetResults;
        activeTab?: TabValue;
      }>
    ) {
      state.datasets = action.payload.datasets;
      state.activeDatasetId = action.payload.activeDatasetId;
      state.activeResults = action.payload.activeResults;
      state.activeTab = action.payload.activeTab ?? "overview";
      state.loading = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchDatasets.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchDatasets.fulfilled, (state, action) => {
        state.loading = false;
        state.datasets = action.payload;
      })
      .addCase(fetchDatasets.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message || "Failed to fetch datasets";
      })
      .addCase(fetchResults.pending, (state) => {
        state.error = null;
      })
      .addCase(fetchResults.fulfilled, (state, action) => {
        state.activeResults = action.payload;
      })
      .addCase(fetchResults.rejected, (state, action) => {
        state.error = action.error.message || "Failed to fetch dataset results";
      });
  },
});

export const { setActiveTab, setActiveDataset, addDataset, seedMockState } = datasetSlice.actions;
export default datasetSlice.reducer;
