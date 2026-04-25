import { app } from "../../scripts/app.js";

const NODE_CLASS = "CodexExecImageGen";
const NODE_TITLE = "Codex Exec ImageGen";
const MAX_CONCURRENCY = 8;

function setupWidget(widget) {
    if (!widget || widget._codexSetup) {
        return;
    }
    widget._codexSetup = true;
    widget._codexOriginalComputeSize = widget.computeSize;
    widget._codexOriginalDraw = widget.draw;
}

function setWidgetVisible(widget, visible) {
    if (!widget) {
        return;
    }
    setupWidget(widget);
    widget._codexVisible = visible;
    widget.computeSize = visible ? widget._codexOriginalComputeSize : () => [0, -4];
    widget.draw = visible ? widget._codexOriginalDraw : () => {};
    setWidgetDomVisible(widget, visible);
}

function setWidgetDomVisible(widget, visible) {
    const display = visible ? "" : "none";
    const visibility = visible ? "" : "hidden";
    for (const element of [
        widget.element,
        widget.inputEl,
        widget.textarea,
        widget.domElement,
    ]) {
        if (element?.style) {
            element.style.display = display;
            element.style.visibility = visibility;
        }
    }
}

function setInputVisible(input, visible) {
    if (!input) {
        return;
    }
    input._codexHidden = !visible;
}

function setupInputVisibility(node) {
    if (node._codexInputsSetup) {
        return;
    }
    node._codexInputsSetup = true;
    node._codexAllInputs = [...(node.inputs ?? [])];
}

function applyInputVisibility(node) {
    setupInputVisibility(node);
    const visibleInputs = orderVisibleInputsForDisplay(
        node._codexAllInputs.filter((input) => !input._codexHidden)
    );
    const hiddenInputs = node._codexAllInputs.filter((input) => input._codexHidden);
    for (const input of hiddenInputs) {
        if (input.link != null) {
            const link = app.graph.links[input.link];
            const originNode = link ? app.graph.getNodeById(link.origin_id) : null;
            if (originNode) {
                originNode.disconnectOutput(link.origin_slot, node);
            }
            input.link = null;
        }
    }
    node.inputs = visibleInputs;
}

function orderVisibleInputsForDisplay(inputs) {
    const baseInputs = inputs.filter((input) => !/^images_\d+$/.test(input.name));
    const numberedImageInputs = inputs
        .filter((input) => /^images_\d+$/.test(input.name))
        .sort((a, b) => Number.parseInt(a.name.split("_")[1], 10) - Number.parseInt(b.name.split("_")[1], 10));
    const imageIndex = baseInputs.findIndex((input) => input.name === "images");
    if (imageIndex < 0) {
        return [...baseInputs, ...numberedImageInputs];
    }
    return [
        ...baseInputs.slice(0, imageIndex + 1),
        ...numberedImageInputs,
        ...baseInputs.slice(imageIndex + 1),
    ];
}

function applyConcurrencyVisibility(node, count) {
    const visibleCount = Math.max(1, Math.min(MAX_CONCURRENCY, Number.parseInt(count, 10) || 1));
    setupInputVisibility(node);
    for (let index = 2; index <= MAX_CONCURRENCY; index += 1) {
        const visible = index <= visibleCount;
        setWidgetVisible(node.widgets?.find((widget) => widget.name === `prompt_${index}`), visible);
        setInputVisible(node._codexAllInputs?.find((input) => input.name === `images_${index}`), visible);
    }
    applyInputVisibility(node);

    requestAnimationFrame(() => {
        node.setSize(node.computeSize());
        node.setDirtyCanvas(true, true);
        app.graph?.setDirtyCanvas(true, true);
        app.canvas?.setDirty(true, true);
    });
}

function setupConcurrencyVisibility(node) {
    const concurrencyWidget = node.widgets?.find((widget) => widget.name === "concurrency_count");
    if (!concurrencyWidget || concurrencyWidget._codexConcurrencyReady) {
        return;
    }

    setupInputVisibility(node);
    concurrencyWidget._codexConcurrencyReady = true;
    const originalCallback = concurrencyWidget.callback;
    concurrencyWidget.callback = function (value) {
        const result = originalCallback?.apply(this, arguments);
        applyConcurrencyVisibility(node, value);
        return result;
    };
    applyConcurrencyVisibility(node, concurrencyWidget.value);
}

app.registerExtension({
    name: "codex.imagegen.dynamic_concurrency",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS && nodeData.display_name !== NODE_TITLE) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            setTimeout(() => setupConcurrencyVisibility(this), 100);
            return result;
        };
    },
});

console.log("[Codex ImageGen] dynamic concurrency extension loaded");
