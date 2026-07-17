function [sum_value, product_value, metadata] = codex_multiout(a, b)
sum_value = a + b;
product_value = a .* b;
metadata = struct('input_class', class(a), 'element_count', numel(a));
end
