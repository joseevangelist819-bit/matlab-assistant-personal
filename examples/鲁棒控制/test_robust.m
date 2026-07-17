function tests = test_robust
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyTrue(testCase, s.result.all_stable);
verifyEqual(testCase, s.result.samples, 20);
end
