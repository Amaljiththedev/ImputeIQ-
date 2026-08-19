"use client";

import { useAppSelector } from "@/store/hooks";
import { Sparkles, FileText, ArrowRight, HelpCircle } from "lucide-react";
import { motion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * Quiet section label. Deliberately low-contrast and small: these are
 * signposts, not content. Apple's deference principle -- the explanation
 * text is what the user came for, so the labelling recedes.
 */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-gray-400 mb-1.5">
      {children}
    </p>
  );
}

export default function ExplanationTab() {
  const { activeResults } = useAppSelector((s) => s.dataset);

  const explanation = activeResults?.explanation_results?.[0];

  if (!explanation) {
    return (
      <div className="space-y-8 pb-12">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
        >
          <h1 className="text-[28px] font-semibold text-gray-900">Explanation</h1>
          <p className="text-[13px] text-gray-600 mt-1.5">
            Plain-language findings for your dataset, column by column.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.05 }}
          className="glass rounded-3xl px-10 py-16 text-center"
        >
          <div className="w-12 h-12 rounded-xl glass-thin flex items-center justify-center mx-auto mb-4">
            <HelpCircle className="w-5 h-5 text-gray-400" strokeWidth={1.5} />
          </div>
          <p className="text-[13px] text-gray-600">
            An explanation hasn&apos;t been generated yet.
          </p>
        </motion.div>
      </div>
    );
  }

  const columns = explanation.columns_json || [];
  // The backend reports "language_model" regardless of provider. This compared
  // against "gemini", a value it stopped emitting when the provider changed, so
  // every genuine model explanation was labelled as template output. Only
  // "template_fallback" actually means the model did not write this.
  const isAI = explanation.generated_by !== "template_fallback";

  return (
    <div className="space-y-8 pb-12">
      {/* Heading + provenance. The badge is a correctness signal, not
          decoration: template output must never be mistaken for model
          output, so the two states get visibly different treatments. */}
      <motion.header
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE }}
        className="flex flex-col sm:flex-row sm:items-center gap-2.5 sm:gap-3.5"
      >
        <h1 className="text-[28px] font-semibold text-gray-900">Explanation</h1>
        {isAI ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-3 py-1 text-[12px] font-medium text-blue-500 self-start sm:self-auto">
            <Sparkles className="w-3.5 h-3.5 shrink-0" />
            Written by the language model
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-bg px-3 py-1 text-[12px] font-medium text-warning-fg self-start sm:self-auto">
            <FileText className="w-3.5 h-3.5 shrink-0" />
            Generated from pipeline results, not the model
          </span>
        )}
      </motion.header>

      {/* Lead finding. Left unwrapped so it reads as the headline rather than
          competing with the cards below. */}
      <motion.p
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE, delay: 0.05 }}
        className="text-[19px] sm:text-[21px] text-gray-900 leading-[1.5] tracking-[-0.015em] max-w-3xl"
      >
        {explanation.overall_summary}
      </motion.p>

      <div className="space-y-5">
        {columns.map((col, idx) => (
          <motion.article
            key={col.target_column ?? idx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE, delay: Math.min(0.1 + idx * 0.04, 0.4) }}
            className="glass glass-interactive rounded-3xl px-7 py-6"
          >
            <h2 className="font-mono text-[14px] font-medium text-gray-900 bg-gray-100 px-3 py-1.5 rounded-full inline-block mb-5">
              {col.target_column}
            </h2>

            {/* Summary carries the finding, so it is set larger than the
                supporting prose beneath it. */}
            <p className="text-[15px] text-gray-900 leading-relaxed mb-6">
              {col.plain_language_summary}
            </p>

            <div className="grid gap-6 sm:grid-cols-2 mb-6">
              <div>
                <SectionLabel>What this means</SectionLabel>
                <p className="text-[13px] text-gray-600 leading-relaxed">
                  {col.what_this_means_for_the_data}
                </p>
              </div>
              <div>
                <SectionLabel>How it was handled</SectionLabel>
                <p className="text-[13px] text-gray-600 leading-relaxed">
                  {col.imputation_explanation}
                </p>
              </div>
            </div>

            <div className="mb-5">
              <SectionLabel>Confidence</SectionLabel>
              <p className="glass-thin rounded-xl px-4 py-3 text-[13px] font-medium text-gray-900 leading-relaxed">
                {col.confidence_note}
              </p>
            </div>

            {/* The single actionable item on the card, and the only place the
                accent colour appears. */}
            <div>
              <SectionLabel>Recommended next step</SectionLabel>
              <div className="flex items-start gap-2.5 rounded-xl bg-blue-500/[0.08] px-4 py-3.5">
                <ArrowRight className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" strokeWidth={2} />
                <span className="text-[13px] font-medium text-blue-700 leading-relaxed">
                  {col.recommended_action}
                </span>
              </div>
            </div>
          </motion.article>
        ))}
      </div>
    </div>
  );
}
