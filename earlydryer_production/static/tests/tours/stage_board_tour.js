import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("earlydryer_production_stage_board", {
    steps: () => [
        {
            content: "The board shows the processing columns",
            trigger: ".o_ed_board .o_ed_column:contains(Received)",
        },
        {
            content: "Open a card",
            trigger: ".o_ed_board .o_ed_card",
            run: "click",
        },
        {
            content: "The side panel lists the garments",
            trigger: ".o_ed_panel h6:contains(Items)",
        },
        {
            content: "Close the panel",
            trigger: ".o_ed_panel .btn-close",
            run: "click",
        },
        {
            content: "Scan bar has the focus again",
            trigger: ".o_ed_scan_input:focus",
        },
    ],
});
