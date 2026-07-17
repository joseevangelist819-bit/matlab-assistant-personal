function tests = test_codex_multiout
tests = functiontests(localfunctions);
end

function testScalarOutputs(testCase)
[sum_value, product_value, metadata] = codex_multiout(3, 4);
verifyEqual(testCase, sum_value, 7);
verifyEqual(testCase, product_value, 12);
verifyEqual(testCase, metadata.element_count, 1);
end
