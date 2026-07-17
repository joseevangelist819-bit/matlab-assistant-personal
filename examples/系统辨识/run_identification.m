root=fileparts(mfilename('fullpath'));rng(20260714);N=600;u=randn(N,1);y=zeros(N,1);noise=0.03*randn(N,1);for k=3:N,y(k)=1.3*y(k-1)-0.4*y(k-2)+0.6*u(k-1)+0.15*u(k-2)+noise(k);end
data=iddata(y,u,0.1);model=arx(data,[2 2 1]);[yhat,fit]=compare(data,model);result=struct('fit_percent',fit,'model_class',class(model),'samples',N);
save(fullfile(root,'result.mat'),'result','data','model','yhat');figure('Visible','off');plot(y);hold on;plot(yhat.OutputData);legend('measured','estimated');grid on;exportgraphics(gcf,fullfile(root,'result.png'));close(gcf);
