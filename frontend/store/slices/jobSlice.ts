import { createSlice, PayloadAction } from "@reduxjs/toolkit";

export type JobPhase = "idle" | "validating" | "diagnosing" | "awaiting_approval" | "imputing" | "explaining" | "complete" | "error";

interface JobState {
  phase: JobPhase;
  currentJobId: string | null;
  logs: string[];
  error: string | null;
}

const initialState: JobState = {
  phase: "idle",
  currentJobId: null,
  logs: [],
  error: null,
};

const jobSlice = createSlice({
  name: "job",
  initialState,
  reducers: {
    setPhase(state, action: PayloadAction<JobPhase>) {
      state.phase = action.payload;
      if (action.payload === "idle") {
        state.currentJobId = null;
      }
    },
    setCurrentJobId(state, action: PayloadAction<string | null>) {
      state.currentJobId = action.payload;
    },
    addLog(state, action: PayloadAction<string>) {
      state.logs.push(action.payload);
    },
    setJobError(state, action: PayloadAction<string>) {
      state.phase = "error";
      state.error = action.payload;
    },
    resetJobs(state) {
      state.phase = "idle";
      state.currentJobId = null;
      state.logs = [];
      state.error = null;
    },
    clearCurrentJob(state) {
      state.currentJobId = null;
    },
    clearLogs(state) {
      state.logs = [];
    },
  },
});

export const { setPhase, setCurrentJobId, addLog, setJobError, resetJobs, clearCurrentJob, clearLogs } = jobSlice.actions;
export default jobSlice.reducer;
