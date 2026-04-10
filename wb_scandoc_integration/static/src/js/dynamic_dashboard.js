/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onMounted } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class OdooDynamicDashboard extends Component {
    setup() {
        this.state = useState({
            scandoc_auth_key: "",
            message: "",
            isLoggedIn: false,
            isVerified: false,
            lastSync: "",
            username: "",
            password: "",
            showPassword: false,
            loginMessage: "",
            isLoading: true,
            credits: {
                scans_limit: 0,
                used_credit: 0,
                remaining_credit: 0,
            },
            transactions: [],
            history: [],

            // ── SEPARATE PAGINATION FOR EACH TABLE ─────────────────────
            pageTransactions: 1,
            pageHistory: 1,
            itemsPerPage: 10,
        });

        onMounted(async () => {
            await this.initAuthState();
        });
    }

    // ──────────────────────────────────────────────────────────────
    // Auth & Init
    // ──────────────────────────────────────────────────────────────
    async initAuthState() {
        this.state.isLoading = true;
        this.state.message = "Checking authentication...";

        try {
            const savedKey = localStorage.getItem("scandoc_auth_key");
            if (savedKey) {
                this.state.authKey = savedKey;
                this.state.isLoggedIn = true;

                const status = await rpc("/wb_odoo_dynamic_dashboard/check_auth_status", {});
                if (status.is_verified) {
                    this.state.isVerified = true;
                    this.state.message = "Welcome back!";
                    this.state.lastSync = this.getCurrentDateTime();
                    await this.loadCredits();
                    return;
                } else {
                    const recoverResult = await rpc("/wb_odoo_dynamic_dashboard/verify_auth_key", {
                        auth_key: savedKey
                    });
                    if (recoverResult.status === "success") {
                        this.state.isVerified = true;
                        this.state.message = "Session restored!";
                        this.state.lastSync = this.getCurrentDateTime();
                        await this.loadCredits();
                        return;
                    }
                }
            }

            this.state.isLoggedIn = false;
            this.state.isVerified = false;
            this.state.message = "Please log in.";
        } catch (e) {
            console.error("Auth init error:", e);
            this.state.message = "Connection issue. Retrying...";
            setTimeout(() => this.initAuthState(), 2000);
        } finally {
            this.state.isLoading = false;
        }
    }

    getCurrentDateTime() {
        return new Date().toLocaleString();
    }

    getMaskedKey(key = "") {
        if (key.length <= 3) return key;
        return "•".repeat(key.length - 3) + key.slice(-3);
    }

    togglePasswordVisibility(ev) {
        const input = document.getElementById("passwordInput");
        const icon = ev.currentTarget.querySelector("i");
        if (!input) return;
        if (input.type === "password") {
            input.type = "text";
            icon.classList.replace("fa-eye-slash", "fa-eye");
        } else {
            input.type = "password";
            icon.classList.replace("fa-eye", "fa-eye-slash");
        }
    }

    // ──────────────────────────────────────────────────────────────
    // TRANSACTIONS PAGINATION
    // ──────────────────────────────────────────────────────────────
    get paginatedTransactions() {
        const start = (this.state.pageTransactions - 1) * this.state.itemsPerPage;
        const end = start + this.state.itemsPerPage;
        return this.state.transactions.slice(start, end);
    }

    get totalPagesTransactions() {
        return Math.max(1, Math.ceil(this.state.transactions.length / this.state.itemsPerPage));
    }

    prevPageTransactions() {
        if (this.state.pageTransactions > 1) this.state.pageTransactions--;
    }

    nextPageTransactions() {
        if (this.state.pageTransactions < this.totalPagesTransactions) this.state.pageTransactions++;
    }

    // ──────────────────────────────────────────────────────────────
    // HISTORY PAGINATION
    // ──────────────────────────────────────────────────────────────
    get paginatedHistory() {
        const start = (this.state.pageHistory - 1) * this.state.itemsPerPage;
        const end = start + this.state.itemsPerPage;
        return this.state.history.slice(start, end);
    }

    get totalPagesHistory() {
        return Math.max(1, Math.ceil(this.state.history.length / this.state.itemsPerPage));
    }

    prevPageHistory() {
        if (this.state.pageHistory > 1) this.state.pageHistory--;
    }

    nextPageHistory() {
        if (this.state.pageHistory < this.totalPagesHistory) this.state.pageHistory++;
    }

    // ──────────────────────────────────────────────────────────────
    // API Calls
    // ──────────────────────────────────────────────────────────────
    async verifyKey() {
        const key = this.state.scandoc_auth_key.trim();
        if (!key) {
            this.state.message = "Please enter a key.";
            return;
        }
        this.state.isLoading = true;
        try {
            const result = await rpc("/wb_odoo_dynamic_dashboard/verify_auth_key", { auth_key: key });
            if (result.status === "success") {
                this.state.isVerified = true;
                this.state.isLoggedIn = true;
                this.state.authKey = key;
                localStorage.setItem("scandoc_auth_key", key);
                this.state.message = "Key verified successfully!";
                this.state.lastSync = this.getCurrentDateTime();
                await this.loadCredits();
            } else {
                this.state.message = result.message || "Invalid key!";
            }
        } catch (err) {
            this.state.message = "Server error.";
            console.error(err);
        } finally {
            this.state.isLoading = false;
        }
    }

    async loadCredits() {
        try {
            const result = await rpc("/wb_odoo_dynamic_dashboard/get_credit_info", {});
            this.state.credits = {
                scans_limit: result.scans_limit || 0,
                used_credit: result.used_credit || 0,
                remaining_credit: result.remaining_credit || 0,
            };
            this.state.transactions = (result.transaction_data || []).sort(
                (a, b) => new Date(b.create_date) - new Date(a.create_date)
            );
            this.state.history = (result.history_data || []).sort(
                (a, b) => new Date(b.auditlog_date) - new Date(a.auditlog_date)
            );
            this.state.authKey = result.authKey || this.state.authKey || "";

            // Reset both paginations when data refreshes
            this.state.pageTransactions = 1;
            this.state.pageHistory = 1;

        } catch (err) {
            console.error("Failed to load credits:", err);
            this.state.message = "Failed to load dashboard data.";
        }
    }

    async discardKey() {
        try {
            await rpc("/wb_odoo_dynamic_dashboard/discard_auth_key", {});
            localStorage.removeItem("scandoc_auth_key");
            Object.assign(this.state, {
                authKey: "", scandoc_auth_key: "", isVerified: false, isLoggedIn: false,
                message: "Key discarded.", lastSync: "", credits: { scans_limit: 0, used_credit: 0, remaining_credit: 0 },
                transactions: [], history: [], pageTransactions: 1, pageHistory: 1
            });
        } catch (err) {
            this.state.message = "Error discarding key.";
        }
    }

    async signIn() {
        this.state.loginMessage = "";
        this.state.isLoading = true;
        try {
            const result = await rpc("/scandoc/login", {
                username: this.state.username,
                password: this.state.password,
            });

            if (result.success && result.authKey) {
                localStorage.setItem("scandoc_auth_key", result.authKey);
                this.state.authKey = result.authKey;
                this.state.isLoggedIn = true;

                const verifyResult = await rpc("/wb_odoo_dynamic_dashboard/verify_auth_key", { auth_key: result.authKey });
                if (verifyResult.status === "success") {
                    this.state.isVerified = true;
                    this.state.message = "Login successful!";
                    this.state.lastSync = this.getCurrentDateTime();
                    await this.loadCredits();
                } else {
                    this.state.message = "Login OK but key verification failed.";
                }
            } else {
                this.state.loginMessage = result.message || "Invalid credentials";
            }
        } catch (err) {
            this.state.loginMessage = "Login failed.";
            console.error(err);
        } finally {
            this.state.isLoading = false;
        }
    }

    async reconfigureKey() {
        try {
            await rpc("/wb_odoo_dynamic_dashboard/reconfigure_auth_key", {});
            localStorage.removeItem("scandoc_auth_key");
            this.state.authKey = "";
            this.state.message = "Please enter your new key.";
            this.state.isVerified = false;
        } catch (err) {
            this.state.message = "Reconfiguration failed.";
        }
    }
}

OdooDynamicDashboard.template = "owl.OdooDynamicDashboard";
registry.category("actions").add("OdooDynamicDashboard", OdooDynamicDashboard);