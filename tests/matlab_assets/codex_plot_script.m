x = linspace(0, 2*pi, 100);
y = sin(x);
figure('Visible', 'off', 'Color', 'white');
plot(x, y, 'LineWidth', 2);
grid on;
xlabel('x'); ylabel('sin(x)'); title('Codex MATLAB Bridge Smoke Test');
