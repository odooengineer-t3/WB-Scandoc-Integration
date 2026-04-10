/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";

export class SentimentDashboard extends Component {
    static props = {
        params: { type: Object, optional: true },
        action: { type: Object, optional: true },
        actionId: { type: [Number, Boolean], optional: true },
        updateActionState: { type: [Function, Boolean], optional: true },
        className: { type: String, optional: true },
    };
    static template = "wb_scandoc_dashboard.SentimentDashboard";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.sentimentChart = useRef("sentimentChart");
        this.chart = null;

        this.state = useState({
            analysis_status: "pending",
            sentiment_score: 0,
            emotional_tone: "—",
            sentiment_color: "#2BBBAD",
            confidence_score: 0,
            communication_style: "—",
            communication_style_color: "#4285F4",
            cultural_fit_score: 0,
            cultural_alignment: "—",
            cultural_alignment_color: "#4285F4",
            motivation_score: 0,
            drive_level: "—",
            drive_color: "#00C851",
            risk_assessment: "—",
            risk_color: "#FF8A00",
            hire_recommendation_score: 0,
            personality_traits: "—",
            confidence_indicators: "—",
            areas_for_improvement: "—",
            areas_for_development: "—",
            collaboration_indicators: "—",
            primary_motivators: "—",
            red_flags_detected: "—",
            positive_indicators: "—",
        });

        // === Get applicant_id robustly ===
        this.getApplicantId = () => {
            return (
                this.props.params?.applicant_id ||
                this.props.action?.context?.applicant_id ||
                this.props.action?.context?.active_id ||
                this.env.context?.active_id ||
                this.env.context?.applicant_id
            );
        };

        this.applicantId = this.getApplicantId();

        // === Load Chart.js ===
        onMounted(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js");
            // Retry analysis after Chart.js loads (in case it was pending)
            if (this.applicantId && this.state.analysis_status !== "done") {
                await this.loadOrRunAnalysis();
            }
        });

        // === Re-run on props update (e.g., context changes) ===
        onWillUpdateProps(async (nextProps) => {
            const newId = this.getApplicantId(nextProps);
            if (newId && newId !== this.applicantId) {
                this.applicantId = newId;
                await this.loadOrRunAnalysis();
            }
        });

        // === Start analysis on mount if ID exists ===
        onWillStart(async () => {
            if (!this.applicantId) {
                console.warn("Applicant ID not found in context. Will retry on mount/update.");
                return;
            }
            await this.loadOrRunAnalysis();
        });
    }

    // === MAIN: Load existing or run new analysis ===
    async loadOrRunAnalysis() {
        if (!this.applicantId) {
            this.notification.add("No applicant selected", { type: "danger" });
            return;
        }

        const fields = [
            "analysis_status", "sentiment_score", "emotional_tone", "sentiment_color",
            "confidence_score", "communication_style", "communication_style_color",
            "cultural_fit_score", "cultural_alignment", "cultural_alignment_color",
            "motivation_score", "drive_level", "drive_color",
            "risk_assessment", "risk_color", "red_flags_count",
            "resume_relevance_score", "hire_recommendation_score",
            "personality_traits", "confidence_indicators", "areas_for_improvement",
            "areas_for_development", "collaboration_indicators",
            "primary_motivators", "red_flags_detected", "positive_indicators"
        ];

        let record;
        try {
            [record] = await this.orm.read("hr.applicant", [this.applicantId], fields);
        } catch (e) {
            console.error("Failed to read applicant:", e);
            this.notification.add("Failed to load applicant data", { type: "danger" });
            return;
        }

        // Update state with loaded data
        this.updateStateFromRecord(record);

        if (record.analysis_status === "done") {
            this.renderChart();
            return;
        }

        // === Run analysis if not done ===
        this.state.analysis_status = "analyzing";
        try {
            const result = await this.orm.call("hr.applicant", "run_resume_analysis", [this.applicantId]);
            if (result && result.success) {
                this.updateStateFromRecord(result.data);
                this.state.analysis_status = "done";
                this.notification.add("Analysis completed successfully!", { type: "success" });
                this.renderChart();
            } else {
                throw new Error(result?.message || "Analysis failed");
            }
        } catch (e) {
            console.error("Analysis error:", e);
            this.state.analysis_status = "failed";
            this.notification.add("Analysis failed: " + (e.message || "Unknown error"), { type: "danger" });
        }
    }

    // === Helper: Update state from record/data ===
    updateStateFromRecord(data) {
        const defaults = {
            analysis_status: "pending",
            sentiment_score: 0,
            emotional_tone: "—",
            sentiment_color: "#2BBBAD",
            confidence_score: 0,
            communication_style: "—",
            communication_style_color: "#4285F4",
            cultural_fit_score: 0,
            cultural_alignment: "—",
            cultural_alignment_color: "#4285F4",
            motivation_score: 0,
            drive_level: "—",
            drive_color: "#00C851",
            risk_assessment: "—",
            risk_color: "#FF8A00",
            hire_recommendation_score: 0,
            personality_traits: "—",
            confidence_indicators: "—",
            areas_for_improvement: "—",
            areas_for_development: "—",
            collaboration_indicators: "—",
            primary_motivators: "—",
            red_flags_detected: "—",
            positive_indicators: "—",
        };

        Object.assign(this.state, defaults, data);
    }

    // === Render Doughnut Chart ===
    renderChart() {
        if (!this.sentimentChart.el || !window.Chart || this.state.analysis_status !== "done") return;

        const score = this.state.sentiment_score || 0;
        const color = this.state.sentiment_color || "#2BBBAD";
        const ctx = this.sentimentChart.el.getContext("2d");

        if (this.chart) this.chart.destroy();

        this.chart = new Chart(ctx, {
            type: "doughnut",
            data: {
                datasets: [{
                    data: [score, 100 - score],
                    backgroundColor: [color, "#E9ECEF"],
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                cutout: "75%",
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false }
                }
            }
        });
    }
}

registry.category("actions").add("wb_scandoc_dashboard.static_dashboard", SentimentDashboard);