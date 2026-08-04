"use client";

import { useEffect, useRef } from "react";
import { io, Socket } from "socket.io-client";
import { useAppDispatch } from "@/store/hooks";
import { setPhase, addLog, setJobError, JobPhase, clearCurrentJob } from "@/store/slices/jobSlice";
import { fetchResults } from "@/store/slices/datasetSlice";
import { getJobStatus } from "@/lib/api";

const SOCKET_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Custom hook that connects to the backend Socket.IO server,
 * joins the room for a specific job, and dispatches Redux actions
 * based on incoming real-time events.
 *
 * Usage:
 *   useSocket(jobId, datasetId);
 *
 * The hook auto-disconnects when the component unmounts or when
 * the job completes.
 */
export function useSocket(jobId: string | null, datasetId: string | null) {
  const dispatch = useAppDispatch();
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    if (!jobId || !datasetId) return;

    const socket = io(SOCKET_URL, {
      transports: ["websocket", "polling"],
      withCredentials: true,
    });

    socketRef.current = socket;

    if (socket.connected) {
      socket.emit("join_job", { job_id: jobId });
    } else {
      socket.on("connect", () => {
        socket.emit("join_job", { job_id: jobId });
      });
    }

    socket.on("job:phase", (data: { phase: string; message?: string }) => {
      dispatch(setPhase(data.phase as JobPhase));
      if (data.message) {
        dispatch(addLog(data.message));
      }
      if (data.phase === "awaiting_approval") {
        dispatch(fetchResults(datasetId));
        socket.disconnect();
      }
    });

    socket.on("job:log", (data: { message: string }) => {
      dispatch(addLog(data.message));
    });

    socket.on("job:complete", () => {
      dispatch(setPhase("complete"));
      dispatch(fetchResults(datasetId));
      dispatch(clearCurrentJob());
      socket.disconnect();
    });

    socket.on("job:error", (data: { message: string }) => {
      dispatch(setJobError(data.message || "An unknown error occurred during processing."));
      socket.disconnect();
    });

    socket.on("connect_error", (err: Error) => {
      console.error("Socket.IO connection error:", err.message);
    });

    // 2-second polling fallback in case WebSocket events are missed or dropped
    let isDone = false;
    const pollInterval = setInterval(async () => {
      if (isDone) return;
      try {
        const job = await getJobStatus(jobId);
        const status = (job.status || "").toLowerCase();
        const phase = (job.current_phase || "").toLowerCase();

        if (status === "complete" || status === "completed" || phase === "complete") {
          isDone = true;
          dispatch(setPhase("complete"));
          dispatch(fetchResults(datasetId));
          dispatch(clearCurrentJob());
          clearInterval(pollInterval);
          socket.disconnect();
        } else if (status === "failed" || status === "error" || phase === "error") {
          isDone = true;
          dispatch(
            setJobError(
              job.error_message || job.error || "An unknown error occurred during processing."
            )
          );
          clearInterval(pollInterval);
          socket.disconnect();
        } else if (status === "awaiting_approval" || phase === "awaiting_approval") {
          isDone = true;
          dispatch(setPhase("awaiting_approval"));
          dispatch(fetchResults(datasetId));
          clearInterval(pollInterval);
          socket.disconnect();
        } else if (status === "running" || status === "pending" || phase) {
          if (phase && phase !== "idle") {
            dispatch(setPhase(phase as JobPhase));
          }
        }
      } catch (err) {
        // Ignore temporary polling errors during execution
      }
    }, 2000);

    return () => {
      isDone = true;
      clearInterval(pollInterval);
      socket.disconnect();
      socketRef.current = null;
    };
  }, [jobId, datasetId, dispatch]);

  return socketRef;
}
