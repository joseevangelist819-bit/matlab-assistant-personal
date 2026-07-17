function tests = test_pid
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyTrue(testCase, s.result.stable);
verifyLessThan(testCase, abs(s.result.final_value - 1), 0.05);
end
